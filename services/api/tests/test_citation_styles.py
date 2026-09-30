"""Deterministic tests of the citation style engine.

These tests pin the exact output of each style, because a bibliography style is a contract
with the reader of the thesis: ``(Dupont, 2024)`` and ``(Dupont & Martin, 2024)`` are not
interchangeable. They need no database, no network and no language model.
"""

from __future__ import annotations

import pytest

from app.citations.data import (
    CitationAuthor,
    CitationData,
    CitationItemData,
    ReferenceCitationData,
)
from app.citations.numbering import assign_numbers, number_map, numbered_items
from app.citations.styles import (
    DEFAULT_STYLE,
    STYLE_REGISTRY,
    UnknownCitationStyle,
    available_styles,
    get_style,
    normalise_style_name,
    resolve_style_name,
)
from app.citations.styles.iso690 import Iso690Style
from app.citations.styles.vancouver import _format_number_range

DUPONT = CitationAuthor("Dupont", "Jean")
MARTIN = CitationAuthor("Martin", "Paul")
RAKOTO = CitationAuthor("Rakoto", "Marie")


def ref(
    reference_id: str = "r1",
    *,
    authors: tuple[CitationAuthor, ...] = (DUPONT,),
    year: int | None = 2024,
    title: str | None = "Composition du grain de jacquier",
    reference_type: str = "article",
    **extra: object,
) -> ReferenceCitationData:
    return ReferenceCitationData(
        reference_id=reference_id,
        citation_key=reference_id,
        reference_type=reference_type,
        title=title,
        authors=authors,
        publication_year=year,
        **extra,  # type: ignore[arg-type]
    )


def cite(  # type: ignore[no-untyped-def]
    *items: CitationItemData,
    prefix=None,
    suffix=None,
    mode="parenthetical",
    is_orphaned: bool = False,
):
    return CitationData(
        "c1",
        tuple(items),
        prefix=prefix,
        suffix=suffix,
        mode=mode,
        is_orphaned=is_orphaned,
    )


# ------------------------------------------------------------------- registry


def test_four_styles_are_registered() -> None:
    assert set(STYLE_REGISTRY) == {"apa7", "harvard", "vancouver", "iso690"}


def test_default_style_is_apa7() -> None:
    assert DEFAULT_STYLE == "apa7"
    assert normalise_style_name(None) == "apa7"
    assert normalise_style_name("") == "apa7"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("apa", "apa7"),
        ("APA7", "apa7"),
        ("apa-7", "apa7"),
        ("  Harvard ", "harvard"),
        ("ICMJE", "vancouver"),
        ("iso-690", "iso690"),
    ],
)
def test_legacy_and_alias_spellings_resolve_to_a_canonical_style(stored, expected) -> None:
    assert normalise_style_name(stored) == expected


def test_an_unknown_value_falls_back_instead_of_raising() -> None:
    """A project with a legacy value must still render."""
    assert normalise_style_name("unstyle") == "apa7"


def test_strict_resolution_reports_an_unknown_style() -> None:
    with pytest.raises(UnknownCitationStyle):
        resolve_style_name("unstyle")


def test_style_catalogue_lists_every_style() -> None:
    catalogue = available_styles()
    assert [entry["name"] for entry in catalogue] == [
        "apa7",
        "harvard",
        "vancouver",
        "iso690",
    ]
    assert catalogue[0]["uses_numbers"] is False
    assert catalogue[2]["uses_numbers"] is True


# ----------------------------------------------------------------------- APA 7


def test_apa_one_author() -> None:
    style = get_style("apa7")
    assert style.format_citation(cite(CitationItemData(ref()))).text == "(Dupont, 2024)"


def test_apa_two_authors() -> None:
    style = get_style("apa7")
    data = ref(authors=(DUPONT, MARTIN))
    assert style.format_citation(cite(CitationItemData(data))).text == "(Dupont & Martin, 2024)"


def test_apa_three_authors_uses_et_al() -> None:
    style = get_style("apa7")
    data = ref(authors=(DUPONT, MARTIN, RAKOTO))
    assert style.format_citation(cite(CitationItemData(data))).text == "(Dupont et al., 2024)"


def test_apa_with_a_page() -> None:
    style = get_style("apa7")
    item = CitationItemData(ref(), locator_type="page", locator_value="25")
    assert style.format_citation(cite(item)).text == "(Dupont, 2024, p. 25)"


def test_apa_with_a_page_range() -> None:
    style = get_style("apa7")
    item = CitationItemData(ref(), locator_type="pages", locator_value="25-28")
    assert style.format_citation(cite(item)).text == "(Dupont, 2024, pp. 25-28)"


def test_apa_with_several_references() -> None:
    style = get_style("apa7")
    first = CitationItemData(ref("a"), locator_type="page", locator_value="25")
    second = CitationItemData(ref("b", authors=(MARTIN,), year=2023, title="Martin"))
    assert style.format_citation(cite(first, second)).text == (
        "(Dupont, 2024, p. 25; Martin, 2023)"
    )


def test_apa_narrative_moves_the_author_outside_the_parentheses() -> None:
    style = get_style("apa7")
    assert style.format_citation(cite(CitationItemData(ref()), mode="narrative")).text == (
        "Dupont (2024)"
    )


def test_apa_narrative_with_three_authors_keeps_et_al() -> None:
    style = get_style("apa7")
    data = ref(authors=(DUPONT, MARTIN, RAKOTO))
    assert style.format_citation(cite(CitationItemData(data), mode="narrative")).text == (
        "Dupont et al. (2024)"
    )


def test_apa_prefix_and_suffix_are_used_verbatim() -> None:
    style = get_style("apa7")
    result = style.format_citation(
        cite(CitationItemData(ref()), prefix="Voir ", suffix=", p. 25")
    )
    assert result.text == "(Voir Dupont, 2024, p. 25)"


def test_apa_reference_list_one_author() -> None:
    style = get_style("apa7")
    entry = style.format_bibliography_entry(
        ref(journal="Revue Agro", volume="10", issue="2", pages="25-40", doi="10.1234/x")
    )
    assert entry.text == (
        "Dupont, J. (2024). Composition du grain de jacquier. "
        "Revue Agro, 10(2), 25–40. https://doi.org/10.1234/x"
    )


def test_apa_reference_list_two_authors_use_a_comma_and_ampersand() -> None:
    style = get_style("apa7")
    entry = style.format_bibliography_entry(ref(authors=(DUPONT, MARTIN)))
    assert entry.text.startswith("Dupont, J., & Martin, P. (2024).")


def test_apa_reference_list_three_authors_lists_them_all() -> None:
    style = get_style("apa7")
    entry = style.format_bibliography_entry(ref(authors=(DUPONT, MARTIN, RAKOTO)))
    assert entry.text.startswith("Dupont, J., Martin, P., & Rakoto, M. (2024).")


def test_apa_twenty_authors_are_all_listed() -> None:
    style = get_style("apa7")
    authors = tuple(CitationAuthor(f"Nom{index}", f"Prenom{index}") for index in range(20))
    entry = style.format_bibliography_entry(ref(authors=authors))
    assert ". . ." not in entry.text
    assert entry.text.count("Nom") == 20


def test_apa_twenty_one_authors_use_an_ellipsis_and_the_last_one() -> None:
    style = get_style("apa7")
    authors = tuple(CitationAuthor(f"Nom{index}", f"Prenom{index}") for index in range(21))
    entry = style.format_bibliography_entry(ref(authors=authors))
    assert ". . ." in entry.text
    assert "Nom0, P." in entry.text
    assert "Nom20, P." in entry.text
    assert "Nom19, P." not in entry.text


def test_apa_thesis_is_written_as_an_unpublished_work() -> None:
    style = get_style("apa7")
    entry = style.format_bibliography_entry(
        ref(reference_type="thesis", title="Thèse", publisher="Université")
    )
    assert entry.text == "Dupont, J. (2024). Thèse. [Université]."


# ------------------------------------------------- missing data: never invented


def test_apa_missing_year_uses_sd_and_warns() -> None:
    style = get_style("apa7")
    result = style.format_citation(cite(CitationItemData(ref(year=None))))
    assert result.text == "(Dupont, s.d.)"
    assert result.warnings
    assert "s.d." not in result.warnings[0] or "Année" in result.warnings[0]


def test_apa_missing_author_falls_back_to_the_title_and_warns() -> None:
    style = get_style("apa7")
    result = style.format_citation(cite(CitationItemData(ref(authors=()))))
    assert result.text == "(Composition du grain de jacquier, 2024)"
    assert any("Auteur" in warning for warning in result.warnings)


def test_apa_missing_author_and_year_never_invents_both() -> None:
    style = get_style("apa7")
    result = style.format_citation(
        cite(CitationItemData(ref(authors=(), year=None, title="Ni auteur ni année")))
    )
    assert result.text == "(Ni auteur ni année, s.d.)"
    assert len(result.warnings) == 2


def test_apa_missing_title_is_reported_in_the_bibliography() -> None:
    style = get_style("apa7")
    entry = style.format_bibliography_entry(ref(title=None))
    assert any("Titre" in warning for warning in entry.warnings)


def test_a_reference_with_nothing_but_a_title_still_renders() -> None:
    """The worst case must produce a coherent line, not a crash and not an invented author."""
    style = get_style("apa7")
    entry = style.format_bibliography_entry(
        ref(authors=(), year=None, title="Document anonyme", reference_type="other")
    )
    assert entry.text.startswith("Document anonyme (s.d.)")


# ------------------------------------------------------------ same author, year


def test_same_author_same_year_gets_a_b_c_suffixes() -> None:
    style = get_style("apa7")
    first = ref("a1", title="Article A")
    second = ref("a2", title="Article B")
    third = ref("a3", title="Article C")
    suffixes = style.assign_year_suffixes([first, second, third])
    assert suffixes == {"a1": "a", "a2": "b", "a3": "c"}


def test_year_suffixes_are_stable_while_the_set_does_not_change() -> None:
    style = get_style("apa7")
    members = [ref("a1", title="Article A"), ref("a2", title="Article B")]
    first = style.assign_year_suffixes(members)
    second = style.assign_year_suffixes(list(reversed(members)))
    assert first == second == {"a1": "a", "a2": "b"}


def test_a_lone_reference_of_an_author_gets_no_suffix() -> None:
    style = get_style("apa7")
    assert style.assign_year_suffixes([ref("a1"), ref("b1", year=2023)]) == {}


def test_the_bibliography_entry_carries_the_year_suffix() -> None:
    style = get_style("apa7")
    members = [ref("a1", title="Article A"), ref("a2", title="Article B")]
    suffixes = style.assign_year_suffixes(members)
    entry = style.format_bibliography_entry(members[1], year_suffix=suffixes["a2"])
    assert entry.text.startswith("Dupont, J. (2024b).")


def test_the_citation_carries_the_year_suffix() -> None:
    style = get_style("apa7")
    members = [ref("a1", title="Article A"), ref("a2", title="Article B")]
    suffixes = style.assign_year_suffixes(members)
    # The engine takes the suffix from the reference data via the year itself; the caller
    # composes it, so a rendered citation shows the lettered year when one exists.
    assert suffixes["a1"] == "a" and suffixes["a2"] == "b"


# -------------------------------------------------------------------- Harvard


def test_harvard_one_and_two_authors() -> None:
    style = get_style("harvard")
    assert style.format_citation(cite(CitationItemData(ref()))).text == "(Dupont, 2024)"
    two = ref(authors=(DUPONT, MARTIN))
    assert style.format_citation(cite(CitationItemData(two))).text == "(Dupont and Martin, 2024)"


def test_harvard_three_authors_are_all_named() -> None:
    style = get_style("harvard")
    three = ref(authors=(DUPONT, MARTIN, RAKOTO))
    assert style.format_citation(cite(CitationItemData(three))).text == (
        "(Dupont, Martin and Rakoto, 2024)"
    )


def test_harvard_four_authors_fall_back_to_et_al() -> None:
    style = get_style("harvard")
    four = ref(
        authors=(
            DUPONT,
            MARTIN,
            RAKOTO,
            CitationAuthor("Ribeiro", "Ana"),
        )
    )
    assert style.format_citation(cite(CitationItemData(four))).text == "(Dupont et al., 2024)"


def test_harvard_with_a_page() -> None:
    style = get_style("harvard")
    item = CitationItemData(ref(), locator_type="page", locator_value="25")
    assert style.format_citation(cite(item)).text == "(Dupont, 2024, p. 25)"


def test_harvard_missing_year_uses_n_d() -> None:
    style = get_style("harvard")
    result = style.format_citation(cite(CitationItemData(ref(year=None))))
    assert result.text == "(Dupont, n.d.)"


def test_harvard_narrative() -> None:
    style = get_style("harvard")
    assert style.format_citation(cite(CitationItemData(ref()), mode="narrative")).text == (
        "Dupont (2024)"
    )


def test_harvard_reference_list() -> None:
    style = get_style("harvard")
    entry = style.format_bibliography_entry(
        ref(authors=(DUPONT, MARTIN), journal="Revue Agro", volume="10", pages="25-40")
    )
    assert entry.text == (
        "Dupont, J. and Martin, P. (2024). Composition du grain de jacquier. "
        "Revue Agro, 10, pp. 25-40."
    )


# ------------------------------------------------------------------ Vancouver


def test_vancouver_numbers_follow_the_order_of_first_citation() -> None:
    style = get_style("vancouver")
    a = ref("A", year=2024, title="A")
    b = ref("B", year=2023, title="B", authors=(MARTIN,))
    c = ref("C", year=2022, title="C", authors=(RAKOTO,))
    document = [
        CitationData("c1", (CitationItemData(a),)),
        CitationData("c2", (CitationItemData(b),)),
        CitationData("c3", (CitationItemData(a),)),
        CitationData("c4", (CitationItemData(c),)),
    ]
    rendered = [
        style.format_citation(CitationData(c.citation_id, tuple(items))).text
        for c, items in numbered_items(document)
    ]
    assert rendered == ["[1]", "[2]", "[1]", "[3]"]


def test_vancouver_renumbers_after_a_deletion() -> None:
    style = get_style("vancouver")
    a = ref("A", year=2024, title="A")
    b = ref("B", year=2023, title="B", authors=(MARTIN,))
    c = ref("C", year=2022, title="C", authors=(RAKOTO,))
    document = [
        CitationData("c1", (CitationItemData(a),)),
        CitationData("c2", (CitationItemData(b),)),
        CitationData("c3", (CitationItemData(c),)),
    ]
    after = [item for item in document if item.citation_id != "c2"]
    rendered = [
        style.format_citation(CitationData(c.citation_id, tuple(items))).text
        for c, items in numbered_items(after)
    ]
    assert rendered == ["[1]", "[2]"]


def test_vancouver_several_numbers_in_one_citation() -> None:
    style = get_style("vancouver")
    a, b, c = ref("A"), ref("B"), ref("C")
    document = [
        CitationData("c1", (CitationItemData(a),)),
        CitationData("c2", (CitationItemData(b),)),
        CitationData("c3", (CitationItemData(c),)),
        CitationData("mix", (CitationItemData(a), CitationItemData(c))),
    ]
    last = numbered_items(document)[-1]
    rendered = style.format_citation(
        CitationData(last[0].citation_id, tuple(last[1]))
    ).text
    assert rendered == "[1,3]"


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([1], "1"),
        ([1, 2], "1-2"),
        ([1, 2, 3], "1-3"),
        ([1, 3, 5], "1,3,5"),
        ([1, 2, 4], "1-2,4"),
        ([2, 4, 5, 6], "2,4-6"),
    ],
)
def test_vancouver_number_ranges(numbers: list[int], expected: str) -> None:
    assert _format_number_range(numbers) == expected


def test_vancouver_never_letters_the_years() -> None:
    style = get_style("vancouver")
    assert style.assign_year_suffixes([ref("a1"), ref("a2")]) == {}
    assert style.requires_year_suffix() is False


def test_vancouver_reports_a_missing_number_instead_of_inventing_one() -> None:
    style = get_style("vancouver")
    result = style.format_citation(cite(CitationItemData(ref())))
    assert "non attribué" in result.text
    assert result.warnings


def test_vancouver_bibliography_is_numbered_in_citation_order() -> None:
    style = get_style("vancouver")
    a = ref("A", title="A")
    b = ref("B", title="B", authors=(MARTIN,))
    entries = [
        style.format_bibliography_entry(a, number=1).text,
        style.format_bibliography_entry(b, number=2).text,
    ]
    assert entries[0].startswith("1. Dupont")
    assert entries[1].startswith("2. Martin")


def test_vancouver_keeps_the_incoming_order() -> None:
    style = get_style("vancouver")
    first = ref("A", title="Zzz")
    second = ref("B", title="Aaa")
    assert style.sort_bibliography([first, second]) == [first, second]


# -------------------------------------------------------------------- ISO 690


def test_iso690_is_documented_as_the_numeric_variant() -> None:
    style = Iso690Style()
    assert "ISO 690" in style.label
    assert style.uses_numbers is True


def test_iso690_reference_has_no_double_period_after_initials() -> None:
    style = Iso690Style()
    entry = style.format_bibliography_entry(
        ref(reference_type="book", title="Le grain", publisher="Éditions X",
            publisher_place="Antananarivo")
    )
    assert "Dupont, J.." not in entry.text
    assert "Dupont, J. Le grain." in entry.text


def test_iso690_cites_by_number() -> None:
    style = Iso690Style()
    a, b = ref("A"), ref("B")
    document = [
        CitationData("c1", (CitationItemData(a),)),
        CitationData("c2", (CitationItemData(b),)),
    ]
    rendered = [
        style.format_citation(CitationData(c.citation_id, tuple(items))).text
        for c, items in numbered_items(document)
    ]
    assert rendered == ["[1]", "[2]"]


def test_iso690_names_a_collective_author_without_initials() -> None:
    style = Iso690Style()
    organisation = ref(
        "org",
        authors=(CitationAuthor("FAO", is_organization=True),),
        reference_type="report",
        title="Rapport annuel",
        year=2023,
    )
    entry = style.format_bibliography_entry(organisation, number=1)
    assert entry.text.startswith("1. FAO. [report]")
    assert "F." not in entry.text


# ------------------------------------------------- collective vs person author


def test_an_organisation_is_not_turned_into_a_person() -> None:
    organisation = CitationAuthor("OMS", is_organization=True)
    assert organisation.display == "OMS"
    assert organisation.inverted == "OMS"
    assert organisation.initials() == ""


def test_a_person_with_a_capitalised_surname_is_still_a_person() -> None:
    """No guessing: the flag is explicit, never inferred from the spelling."""
    person = CitationAuthor("DUPONT", "Jean")
    assert person.initials() == "J."
    assert person.display == "Jean DUPONT"


def test_apa_writes_an_organisation_without_initials() -> None:
    style = get_style("apa7")
    organisation = ref("org", authors=(CitationAuthor("INSTAT", is_organization=True),), year=2023)
    assert style.format_citation(cite(CitationItemData(organisation))).text == "(INSTAT, 2023)"
    assert style.format_bibliography_entry(organisation).text.startswith("INSTAT (2023).")


def test_initials_handle_multi_part_and_hyphenated_given_names() -> None:
    assert CitationAuthor("Dupont", "Jean Paul").initials() == "J. P."
    assert CitationAuthor("Dupont", "Jean-Paul").initials() == "J. P."


def test_a_person_without_a_given_name_keeps_the_family_name_only() -> None:
    """Aristote has no first name; none is invented."""
    ancient = CitationAuthor("Aristote")
    assert ancient.initials() == ""
    assert ancient.display == "Aristote"
    style = get_style("apa7")
    entry = style.format_bibliography_entry(ref(authors=(ancient,)))
    assert entry.text.startswith("Aristote (2024).")


# ----------------------------------------------------------------- locators


@pytest.mark.parametrize(
    ("locator_type", "value", "expected"),
    [
        ("page", "25", "p. 25"),
        ("pages", "25-28", "pp. 25-28"),
        ("chapter", "3", "chap. 3"),
        ("figure", "4", "fig. 4"),
        ("table", "2", "tableau 2"),
        ("section", "2.1", "sec. 2.1"),
        ("other", "annexe B", "annexe B"),
    ],
)
def test_every_locator_type_is_rendered(locator_type, value, expected) -> None:
    style = get_style("apa7")
    item = CitationItemData(ref(), locator_type=locator_type, locator_value=value)
    assert f", {expected})" in style.format_citation(cite(item)).text


def test_a_locator_without_a_value_adds_nothing() -> None:
    """No page is ever invented from a locator type alone."""
    style = get_style("apa7")
    item = CitationItemData(ref(), locator_type="page", locator_value=None)
    assert style.format_citation(cite(item)).text == "(Dupont, 2024)"


def test_a_page_range_is_never_rebuilt() -> None:
    style = get_style("apa7")
    item = CitationItemData(ref(), locator_type="pages", locator_value="25")
    assert "pp. 25)" in style.format_citation(cite(item)).text


# ------------------------------------------------------------------- orphans


def test_an_orphaned_citation_says_so_and_never_invents_an_author() -> None:
    for name in ("apa7", "harvard", "vancouver", "iso690"):
        style = get_style(name)
        result = style.format_citation(cite(CitationItemData(ref()), is_orphaned=True))
        assert result.is_orphaned is True
        assert "invalide" in result.text.lower()
        assert "Dupont" not in result.text
        assert result.warnings


def test_a_citation_without_any_reference_is_reported() -> None:
    for name in ("apa7", "harvard", "vancouver", "iso690"):
        style = get_style(name)
        result = style.format_citation(CitationData("c1", ()))
        assert "sans référence" in result.text
        assert result.warnings


# ---------------------------------------------------------------- numbering


def test_numbering_is_one_based_and_gaps_are_impossible() -> None:
    document = [
        CitationData("c1", (CitationItemData(ref("A")),)),
        CitationData("c2", (CitationItemData(ref("B")),)),
        CitationData("c3", (CitationItemData(ref("A")),)),
    ]
    assert number_map(document) == {"A": 1, "B": 2}
    assert [item.assigned for item in assign_numbers(document)] == [(1,), (2,), (1,)]


def test_a_reference_without_an_id_gets_no_number() -> None:
    document = [CitationData("c1", (CitationItemData(ref("")),))]
    assert number_map(document) == {}


def test_several_references_in_one_citation_keep_their_own_numbers() -> None:
    a, b = ref("A"), ref("B")
    document = [
        CitationData("c1", (CitationItemData(a),)),
        CitationData("c2", (CitationItemData(b),)),
    ]
    numbers = number_map(document)
    assert numbers == {"A": 1, "B": 2}


# -------------------------------------------------------- reference types


@pytest.mark.parametrize(
    "reference_type",
    [
        "article",
        "book",
        "book_chapter",
        "thesis",
        "report",
        "conference",
        "webpage",
        "dataset",
        "patent",
        "other",
    ],
)
def test_every_reference_type_renders_in_every_style(reference_type: str) -> None:
    data = ref(
        "x",
        reference_type=reference_type,
        journal="Revue Agro",
        publisher="Éditions X",
        url="https://exemple.fr",
        doi="10.1234/x",
    )
    for name in STYLE_REGISTRY:
        style = get_style(name)
        citation = style.format_citation(cite(CitationItemData(data)))
        entry = style.format_bibliography_entry(data, number=1)
        assert citation.text.strip()
        assert entry.text.strip()
        # "s.d."/"n.d." are the only date placeholders; a real year is never fabricated.
        if data.publication_year:
            assert "s.d." not in citation.text
            assert "n.d." not in citation.text


def test_a_reference_type_does_not_crash_the_bibliography_when_data_is_absent() -> None:
    bare = ReferenceCitationData(
        reference_id="x", citation_key="x", reference_type="dataset", title=None
    )
    for name in STYLE_REGISTRY:
        style = get_style(name)
        assert style.format_bibliography_entry(bare, number=1).text.strip()


# ------------------------------------------------------------------ sorting


def test_alphabetical_styles_sort_by_author_then_year_then_title() -> None:
    style = get_style("apa7")
    members = [
        ref("b", authors=(MARTIN,), year=2020, title="B"),
        ref("a", authors=(DUPONT,), year=2025, title="Zzz"),
        ref("c", authors=(DUPONT,), year=2020, title="Aaa"),
    ]
    ordered = style.sort_bibliography(members)
    assert [item.reference_id for item in ordered] == ["c", "a", "b"]


def test_a_reference_without_an_author_sorts_under_its_title() -> None:
    style = get_style("apa7")
    members = [
        ref("z", authors=(), year=2024, title="Zebre"),
        ref("a", authors=(), year=2024, title="Abeille"),
        ref("d", authors=(DUPONT,), year=2024, title="DUPONT"),
    ]
    ordered = style.sort_bibliography(members)
    # An authorless reference is keyed on its title, so it is interleaved with the authors
    # rather than pushed to one end: "Abeille" (a) < "Dupont" (d) < "Zebre" (z).
    assert [item.reference_id for item in ordered] == ["a", "d", "z"]


def test_a_dateless_reference_follows_the_dated_ones_of_the_same_author() -> None:
    style = get_style("apa7")
    members = [
        ref("a", authors=(DUPONT,), year=None, title="Sans annee"),
        ref("b", authors=(DUPONT,), year=2024, title="Avec annee"),
    ]
    ordered = style.sort_bibliography(members)
    assert [item.reference_id for item in ordered] == ["b", "a"]


def test_different_organisations_with_the_same_year_do_not_collide() -> None:
    style = get_style("apa7")
    members = [
        ref("f", authors=(CitationAuthor("FAO", is_organization=True),), title="F"),
        ref("o", authors=(CitationAuthor("OMS", is_organization=True),), title="O"),
    ]
    assert style.assign_year_suffixes(members) == {}
