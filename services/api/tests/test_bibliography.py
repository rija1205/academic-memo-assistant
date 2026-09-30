"""Unit tests for the bibliography: normalisation, authors, parsers, duplicates, security."""

from __future__ import annotations

import pytest

from app.bibliography.authors import (
    format_author_list,
    normalize_orcid,
    parse_author_name,
    parse_authors,
    parse_ris_authors,
)
from app.bibliography.duplicates import (
    DuplicateLevel,
    ReferenceSummary,
    compare,
    find_duplicates,
    plan_merge,
)
from app.bibliography.parsers import (
    export_bibtex,
    export_ris,
    parse_bibtex,
    parse_ris,
)
from app.bibliography.schemas import (
    MAX_AUTHORS,
    MAX_KEYWORDS,
    AuthorInput,
    ImportErrorItem,
    ReferenceCreateRequest,
    ReferenceUpdateRequest,
)
from app.bibliography.service import build_citation_key, slugify
from app.core.normalize import (
    is_valid_doi,
    normalize_doi,
    normalize_title,
    normalize_url,
    title_similarity,
)

# --------------------------------------------------------------------------- DOI


@pytest.mark.parametrize(
    "raw",
    [
        "10.1234/example",
        "https://doi.org/10.1234/example",
        "http://doi.org/10.1234/example",
        "https://dx.doi.org/10.1234/example",
        "http://dx.doi.org/10.1234/example",
        "doi:10.1234/example",
        "  https://DOI.org/10.1234/EXAMPLE  ",
    ],
)
def test_doi_variants_normalise_to_the_same_canonical_form(raw: str) -> None:
    assert normalize_doi(raw) == "10.1234/example"


def test_doi_is_case_insensitive_on_the_suffix() -> None:
    assert normalize_doi("10.1234/AbC") == normalize_doi("10.1234/abc")


@pytest.mark.parametrize(
    "raw", ["", "   ", None, "pas un doi", "10.1234/", "https://example.com/10.1234/x"]
)
def test_invalid_doi_stays_none_and_is_never_invented(raw) -> None:
    assert normalize_doi(raw) is None
    assert is_valid_doi(raw) is False


def test_doi_that_looks_like_a_url_is_rejected() -> None:
    """A URL that is not a DOI resolver must not be turned into a DOI."""
    assert normalize_doi("https://www.perennature.fr/article/xyz") is None


# -------------------------------------------------------------------------- URL


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1234/x", "https://doi.org/10.1234/x"),
        ("HTTP://EXAMPLE.ORG:80/Path", "http://example.org/Path"),
        ("https://example.org:443/a?b=c#d", "https://example.org/a?b=c#d"),
        ("example.org/page", "https://example.org/page"),
    ],
)
def test_url_normalisation_keeps_the_path(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_url_with_a_query_is_not_broken() -> None:
    assert normalize_url("https://x.fr/a?b=1&c=2") == "https://x.fr/a?b=1&c=2"


def test_invalid_url_scheme_is_rejected() -> None:
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("") is None


# ----------------------------------------------------------------------- authors


def test_bibtex_style_author_is_split_on_the_comma() -> None:
    author = parse_author_name("Dupont, Jean", 1)
    assert author.family_name == "Dupont"
    assert author.given_name == "Jean"


def test_plain_author_takes_the_last_token_as_the_family_name() -> None:
    author = parse_author_name("Jean Dupont", 1)
    assert author.family_name == " Dupont".strip() == "Dupont"
    assert author.given_name == "Jean"


def test_multi_word_given_name_is_preserved() -> None:
    author = parse_author_name("Jean Paul Dupont", 1)
    assert author.family_name == "Dupont"
    assert author.given_name == "Jean Paul"


def test_single_token_author_has_no_given_name() -> None:
    author = parse_author_name("Aristote", 1)
    assert author.family_name == "Aristote"
    assert author.given_name is None


def test_author_order_is_preserved_and_numbered_from_one() -> None:
    authors = parse_authors("Dupont, Jean and Rakoto, Marie and Martin, Paul")
    assert [author.position for author in authors] == [1, 2, 3]
    assert [author.family_name for author in authors] == ["Dupont", "Rakoto", "Martin"]


def test_ris_authors_keep_their_order() -> None:
    authors = parse_ris_authors(["Dupont, Jean", "Rakoto, Marie"])
    assert [author.family_name for author in authors] == ["Dupont", "Rakoto"]


def test_empty_author_input_produces_nothing() -> None:
    assert parse_authors(None) == []
    assert parse_authors("") == []


def test_bibtex_author_list_round_trip() -> None:
    authors = parse_authors("Dupont, Jean and Rakoto, Marie")
    text = format_author_list(authors, bibtex=True)
    assert text == "Dupont, Jean and Rakoto, Marie"
    again = parse_authors(text)
    assert [author.family_name for author in again] == ["Dupont", "Rakoto"]


def test_orcid_is_normalised_and_validated_on_shape_only() -> None:
    assert normalize_orcid("https://orcid.org/0000-0002-1825-0097") == "0000000218250097"
    assert normalize_orcid("0000-0002-1825-0097") == "0000000218250097"
    assert normalize_orcid("pas un orcid") is None
    assert normalize_orcid("") is None


# ------------------------------------------------------------------------ BibTeX


BIBTEX = """
@article{dupont2024,
  author  = {Dupont, Jean and Rakoto, Marie},
  title   = {Composition nutritionnelle du grain de jacquier},
  journal = {Revue Agro},
  year    = {2024},
  volume  = {10},
  number  = {2},
  pages   = {10--20},
  doi     = {https://doi.org/10.1234/EXAMPLE},
  keywords = {jacquier, nutrition},
  abstract = {Une etude sur le jacquier.},
  issn = {1234-5678}
}
@book{rakoto2020, author={Rakoto Marie}, title={Le grain}, year={2020}, isbn={978-2-1234}}
@weirdtype{inconnu1, title={Type non standard}}
"""


def test_bibtex_import_reads_every_expected_field() -> None:
    result = parse_bibtex(BIBTEX)
    assert len(result.references) == 3
    article = result.references[0]
    assert article.reference_type == "article"
    assert article.title == "Composition nutritionnelle du grain de jacquier"
    assert article.journal == "Revue Agro"
    assert article.publication_year == 2024
    assert article.volume == "10"
    assert article.issue == "2"
    assert article.doi == "10.1234/example"
    assert article.doi_original == "https://doi.org/10.1234/EXAMPLE"
    assert article.keywords == ["jacquier", "nutrition"]
    assert article.issn == "1234-5678"
    assert [author.family_name for author in article.authors] == ["Dupont", "Rakoto"]


def test_unknown_bibtex_type_is_kept_as_other_and_reported() -> None:
    result = parse_bibtex(BIBTEX)
    third = result.references[2]
    assert third.reference_type == "other"
    assert third.entry_type == "weirdtype"
    assert third.errors  # the author is warned, the information is not lost


def test_bibtex_absent_fields_stay_none() -> None:
    result = parse_bibtex("@misc{cle, title={Sans annee}}")
    reference = result.references[0]
    assert reference.title == "Sans annee"
    assert reference.publication_year is None
    assert reference.doi is None
    assert reference.journal is None


def test_bibtex_braced_fields_and_nested_braces() -> None:
    result = parse_bibtex("@article{a, title={Composition {du} grain}, year={2024}}")
    assert result.references[0].title == "Composition {du} grain"


def test_bibtex_entries_without_a_balanced_brace_are_reported_not_crashed() -> None:
    result = parse_bibtex("@article{casse, title={sans accolade")
    assert result.references == []
    assert result.errors


def test_empty_bibtex_file_returns_a_clear_error() -> None:
    result = parse_bibtex("")
    assert result.references == []
    assert "Fichier BibTeX vide" in result.errors[0] or "Aucune entrée BibTeX" in result.errors[0]


def test_bibtex_import_is_capped_by_max_entries() -> None:
    content = "\n".join(f"@article{{k{i}, title={{T{i}}}}}" for i in range(50))
    result = parse_bibtex(content, max_entries=10)
    assert len(result.references) == 10
    assert any("Limite atteinte" in message for message in result.errors)


def test_bibtex_never_evaluates_content() -> None:
    """A hostile entry is plain text, never an instruction nor an expression."""
    hostile = '@article{x, title={$(rm -rf /)}, note={__import__("os")}}'
    result = parse_bibtex(hostile)
    assert result.references[0].title == "$(rm -rf /)"
    assert result.references[0].notes == '__import__("os")'


# ----------------------------------------------------------------------------- RIS


RIS = """TY  - JOUR
AU  - Dupont, Jean
AU  - Rakoto, Marie
TI  - Composition du jacquier
JO  - Revue Agro
PY  - 2024
VL  - 10
IS  - 2
SP  - 10
EP  - 20
DO  - https://doi.org/10.1234/EX
UR  - https://revue.ag/2024/1
PB  - Edit X
KW  - jacquier
KW  - nutrition
AB  - Resume de l'etude.
SN  - ISSN 1234-5678
ER  -

TY  - THES
AU  - Rakoto Marie
TI  - These de doctorat
PY  - 2020
PB  - Universite
CY  - Antananarivo
ER  -
"""


def test_ris_import_reads_every_expected_field() -> None:
    result = parse_ris(RIS)
    assert len(result.references) == 2
    first = result.references[0]
    assert first.reference_type == "article"
    assert first.title == "Composition du jacquier"
    assert first.journal == "Revue Agro"
    assert first.publication_year == 2024
    assert first.volume == "10"
    assert first.issue == "2"
    assert first.pages == "10-20"
    assert first.doi == "10.1234/ex"
    assert first.keywords == ["jacquier", "nutrition"]
    assert first.issn == "1234-5678"
    assert [author.family_name for author in first.authors] == ["Dupont", "Rakoto"]


def test_ris_thesis_maps_to_thesis_type() -> None:
    result = parse_ris(RIS)
    assert result.references[1].reference_type == "thesis"
    assert result.references[1].publisher_place == "Antananarivo"


def test_ris_unknown_type_is_kept_as_other() -> None:
    result = parse_ris("TY  - ZZZZ\nTI  - Mystere\nER  -")
    assert result.references[0].reference_type == "other"
    assert result.references[0].entry_type == "ZZZZ"


def test_empty_ris_file_returns_a_clear_error() -> None:
    result = parse_ris("   ")
    assert result.references == []
    assert result.errors


# ------------------------------------------------------------------ round trips


def test_bibtex_round_trip_preserves_important_metadata() -> None:
    original = parse_bibtex(BIBTEX).references
    exported = export_bibtex(original)
    again = parse_bibtex(exported).references
    assert len(again) == len(original)
    for before, after in zip(original, again, strict=True):
        assert after.reference_type == before.reference_type
        assert after.title == before.title
        assert after.journal == before.journal
        assert after.publication_year == before.publication_year
        assert after.volume == before.volume
        assert after.issue == before.issue
        assert after.doi == before.doi
        assert after.issn == before.issn
        assert after.keywords == before.keywords
        assert [a.family_name for a in after.authors] == [a.family_name for a in before.authors]
        assert [a.given_name for a in after.authors] == [a.given_name for a in before.authors]


def test_ris_round_trip_preserves_important_metadata() -> None:
    original = parse_ris(RIS).references
    exported = export_ris(original)
    again = parse_ris(exported).references
    assert len(again) == len(original)
    for before, after in zip(original, again, strict=True):
        assert after.reference_type == before.reference_type
        assert after.title == before.title
        assert after.publication_year == before.publication_year
        assert after.journal == before.journal
        assert after.doi == before.doi
        assert after.pages == before.pages
        assert after.keywords == before.keywords
        assert [a.family_name for a in after.authors] == [a.family_name for a in before.authors]


def test_bibtex_export_escapes_special_characters() -> None:
    parsed = parse_bibtex(
        "@article{x, title={Cout & recettes_\\$100}, author={Dupont, Jean}, year={2024}}"
    ).references[0]
    exported = export_bibtex([parsed])
    assert r"\&" in exported
    assert r"\_" in exported
    again = parse_bibtex(exported).references[0]
    assert "Cout" in again.title and "recettes" in again.title


def test_export_of_an_empty_list_is_empty_not_broken() -> None:
    assert export_bibtex([]) == ""
    assert export_ris([]) == ""


# --------------------------------------------------------------------- duplicates


def summary(**overrides) -> ReferenceSummary:
    base = {
        "id": overrides.pop("id", "id-1"),
        "citation_key": "dupont2024",
        "title": "Composition du grain de jacquier",
        "publication_year": 2024,
        "doi": None,
        "author_families": ("dupont",),
    }
    base.update(overrides)
    return ReferenceSummary(**base)


def test_same_doi_is_an_exact_duplicate() -> None:
    left = summary(doi="10.1234/x")
    right = summary(id="id-2", doi="https://doi.org/10.1234/X", title="Autre titre")
    match = compare(left, right)
    assert match is not None
    assert match.level == DuplicateLevel.EXACT
    assert "DOI identique" in match.reason


def test_same_title_and_year_is_a_strong_duplicate() -> None:
    right = summary(id="id-2", title="COMPOSITION  du GRAIN, de jacquier!", citation_key="k2")
    match = compare(summary(), right)
    assert match is not None
    assert match.level == DuplicateLevel.STRONG


def test_similar_title_and_shared_author_is_possible() -> None:
    right = summary(
        id="id-2",
        title="Composition nutritionnelle du grain de jacquier au Madagascar",
        citation_key="k2",
    )
    match = compare(summary(title="Composition nutritionnelle du grain de jacquier"), right)
    assert match is not None
    assert match.level == DuplicateLevel.POSSIBLE
    assert match.shared_authors == ("dupont",)


def test_different_references_are_not_duplicates() -> None:
    right = summary(
        id="id-2",
        title="Stabilisation urbaine en Amerique latine",
        citation_key="ribeiro2021",
        publication_year=2021,
        author_families=("ribeiro",),
    )
    assert compare(summary(), right) is None


def test_duplicate_report_groups_by_level() -> None:
    current = summary(
        title="Composition nutritionnelle du grain de jacquier", doi="10.1234/x"
    )
    others = [
        summary(id="e1", doi="10.1234/x", citation_key="e1"),
        summary(
            id="s1",
            citation_key="s1",
            title="Composition nutritionnelle du grain de jacquier",
        ),
        summary(
            id="p1",
            citation_key="p1",
            title="Composition nutritionnelle du grain de jacquier au Madagascar",
        ),
    ]
    report = find_duplicates(current, others)
    assert report.has_matches
    assert len(report.exact) == 1
    assert len(report.strong) == 1
    assert len(report.possible) == 1
    assert report.as_dict()["has_duplicates"] is True


def test_comparing_a_reference_with_itself_is_not_a_duplicate() -> None:
    assert compare(summary(), summary()) is None


def test_merge_plan_never_loses_a_value() -> None:
    plan = plan_merge(
        target=summary(),
        source=summary(id="id-2"),
        target_fields={"title": "Titre garde", "doi": None, "pages": None},
        source_fields={"title": "Autre", "doi": "10.1/a", "pages": "10-20", "notes": "Note B"},
        source_author_count=2,
        overlapping_tag_count=1,
    )
    assert plan.fills["doi"] == "10.1/a"
    assert plan.fills["pages"] == "10-20"
    assert "title" not in plan.fills
    assert plan.notes_appended is True
    assert plan.authors_to_move == 2


# ------------------------------------------------------------------- title match


def test_title_similarity_is_bounded_and_ordered() -> None:
    assert title_similarity("Composition du grain", "Composition du grain") == 1.0
    assert title_similarity("Composition du grain", "") == 0.0
    close = title_similarity(
        "Composition du grain de jacquier",
        "Composition du grain de jacquier au Madagascar",
    )
    far = title_similarity(
        "Composition du grain de jacquier",
        "Stabilisation urbaine en Amerique latine",
    )
    assert close > far
    assert 0.0 <= far <= 1.0


def test_normalise_title_removes_case_accents_and_punctuation() -> None:
    assert normalize_title("L'Analyse : Résultats!") == "l analyse resultats"


# --------------------------------------------------------------------- citation key


def test_citation_key_is_derived_from_first_author_and_year() -> None:
    parsed = parse_bibtex(BIBTEX).references[0]
    key = build_citation_key(
        authors=[AuthorInput(family_name="Dupont")],
        publication_year=2024,
        title="Composition",
    )
    assert key == "dupont2024"
    assert parsed.citation_key == "dupont2024"


def test_citation_key_falls_back_to_the_title_without_a_year() -> None:
    key = build_citation_key(
        authors=[], publication_year=None, title="Le grain de jacquier", fallback="ref"
    )
    assert key == "le-grain-de-jacquiernd"


def test_slugify_strips_accents_and_punctuation() -> None:
    assert slugify("Rakoto & Fils, É.") == "rakoto-fils-e"


# ------------------------------------------------------------------------ security


def test_oversized_field_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValueError):
        ReferenceCreateRequest(title="x" * 1001)


def test_too_many_keywords_are_rejected() -> None:
    with pytest.raises(ValueError):
        ReferenceCreateRequest(keywords=[f"k{i}" for i in range(MAX_KEYWORDS + 1)])


def test_too_many_authors_are_rejected() -> None:
    with pytest.raises(ValueError):
        ReferenceCreateRequest(
            authors=[{"family_name": f"A{i}"} for i in range(MAX_AUTHORS + 1)]  # type: ignore
        )


def test_year_outside_the_plausible_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        ReferenceCreateRequest(publication_year=900)


def test_blank_values_become_none_instead_of_empty_strings() -> None:
    payload = ReferenceCreateRequest(title="   ", journal="", doi="  ")
    assert payload.title is None
    assert payload.journal is None
    assert payload.doi is None


def test_update_request_only_reports_the_fields_it_carries() -> None:
    payload = ReferenceUpdateRequest(title="Nouveau")
    assert "title" in payload.model_dump(exclude_unset=True)
    assert "journal" not in payload.model_dump(exclude_unset=True)


def test_import_error_item_is_constructible() -> None:
    item = ImportErrorItem(message="Entrée ignorée", citation_key="abc")
    assert item.message == "Entrée ignorée"


# ------------------------------------------------------- permissions wiring

def _role_requirement(method: str, path_suffix: str) -> str:
    """Return the project role a route requires, read from the route itself.

    A permission test that needs a database cannot run in every environment. Reading the
    dependency off the route still catches the mistake that actually happens: wiring the
    wrong guard onto an endpoint, for example allowing a reader to delete a reference.
    """
    from fastapi.routing import APIRoute

    from app.bibliography.router import router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if method not in route.methods or not route.path.endswith(path_suffix):
            continue
        for dependency in route.dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name.startswith("require_project_"):
                return name
        return "aucune"
    raise AssertionError(f"Route introuvable : {method} {path_suffix}")


@pytest.mark.parametrize(
    ("method", "path_suffix", "expected"),
    [
        ("GET", "/bibliography", "require_project_reader"),
        ("GET", "/bibliography/search", "require_project_reader"),
        ("GET", "/bibliography/stats", "require_project_reader"),
        ("GET", "/bibliography/export/{export_format}", "require_project_reader"),
        ("GET", "/bibliography/{reference_id}", "require_project_reader"),
        ("GET", "/bibliography/{reference_id}/duplicates", "require_project_reader"),
        ("POST", "/bibliography", "require_project_editor"),
        ("PATCH", "/bibliography/{reference_id}", "require_project_editor"),
        ("POST", "/bibliography/import/{import_format}", "require_project_editor"),
        ("POST", "/bibliography/{reference_id}/merge", "require_project_editor"),
        ("DELETE", "/bibliography/{reference_id}", "require_project_owner"),
    ],
)
def test_each_route_requires_the_expected_role(
    method: str, path_suffix: str, expected: str
) -> None:
    assert _role_requirement(method, path_suffix) == expected


def test_reading_a_reference_of_another_project_is_a_404_not_a_data_leak() -> None:
    """The reference lookup is scoped by project, and an unknown project answers 404.

    ``get_reference`` filters on both ``project_id`` and the identifier, so a valid
    identifier from another project simply does not exist as far as the caller is concerned.
    """
    import inspect

    from app.bibliography.service import get_reference

    source = inspect.getsource(get_reference)
    assert "BibliographicReference.project_id == project_id" in source
    assert "BibliographicReference.id == reference_id" in source
    assert "HTTP_404" in source or "404" in source


def test_every_mutation_route_is_csrf_protected() -> None:
    """No state-changing bibliography route may be reachable without a CSRF token."""
    from fastapi.routing import APIRoute

    from app.bibliography.router import router

    checked = 0
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.methods is None or not (route.methods & {"POST", "PATCH", "PUT", "DELETE"}):
            continue
        checked += 1
        names = [
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        ]
        assert "require_csrf" in names, f"{route.path} n'exige pas de jeton CSRF."
    assert checked >= 5


def test_export_rejects_an_unsupported_format() -> None:
    from app.bibliography.service import render_export

    with pytest.raises(Exception) as error:
        render_export([], "endnote")
    assert "non support" in str(error.value).lower() or "400" in str(error.value)


def test_import_rejects_an_unsupported_format() -> None:
    from app.bibliography.service import parse_import

    with pytest.raises(Exception) as error:
        parse_import("x", "csv", max_entries=10)
    assert "non support" in str(error.value).lower() or "400" in str(error.value)


def test_source_link_must_belong_to_the_same_project() -> None:
    """Linking a reference to a source of another project is refused, not silently ignored."""
    import inspect

    from app.bibliography.service import _validate_source

    source = inspect.getsource(_validate_source)
    assert "Source.project_id == project_id" in source
    assert "Source.deleted_at.is_(None)" in source
    assert "422" in source
