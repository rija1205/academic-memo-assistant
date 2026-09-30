"""Tests of the citation service that need no database.

These cover the logic that is not part of the style engine: walking a Tiptap document,
detecting a legacy node, ordering citations, and the wiring of the routes to the roles. The
parts that genuinely need PostgreSQL (persistence, foreign keys, cross-project isolation at
the SQL level) are not testable here and are reported as not executed.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from app.citations import service
from app.citations.schemas import (
    MAX_REFERENCES_PER_CITATION,
    CitationCreateRequest,
    CitationItemInput,
    CitationUpdateRequest,
    PreviewRequest,
)
from app.citations.service import (
    collect_citation_nodes,
    resolve_project_style,
    to_reference_data,
)
from app.citations.styles import DEFAULT_STYLE, get_style
from app.models.bibliography import BibliographicReference, ReferenceAuthor

# ------------------------------------------------------ Tiptap document walking


def citation_node(citation_id: str, reference_ids: list[str], **attrs: object) -> dict:
    return {
        "type": "citation",
        "attrs": {
            "citationId": citation_id,
            "referenceIds": reference_ids,
            **attrs,
        },
    }


def test_a_single_citation_node_is_collected() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [citation_node("n1", ["ref-1"])]},
        ],
    }
    nodes = collect_citation_nodes(document)
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "n1"
    assert nodes[0]["reference_ids"] == ["ref-1"]


def test_citations_are_collected_in_document_order() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [citation_node("n1", ["a"])]},
            {"type": "heading", "content": [{"type": "text", "text": "Titre"}]},
            {
                "type": "blockquote",
                "content": [{"type": "paragraph", "content": [citation_node("n2", ["b", "c"])]}],
            },
        ],
    }
    assert [node["node_id"] for node in collect_citation_nodes(document)] == ["n1", "n2"]


def test_several_references_in_one_node_are_kept_in_order() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [citation_node("n1", ["b", "a", "c"])]},
        ],
    }
    assert collect_citation_nodes(document)[0]["reference_ids"] == ["b", "a", "c"]


def test_a_citation_inside_a_table_cell_is_found() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [citation_node("deep", ["x"])],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    assert [node["node_id"] for node in collect_citation_nodes(document)] == ["deep"]


def test_a_document_without_citation_returns_nothing() -> None:
    document = {"type": "doc", "content": [{"type": "paragraph", "content": []}]}
    assert collect_citation_nodes(document) == []


def test_a_malformed_document_does_not_raise() -> None:
    """A document written by an older version must still load."""
    for document in (None, {}, {"type": "doc"}, {"content": "nope"}, {"content": [1, 2, 3]}):
        assert collect_citation_nodes(document) == []  # type: ignore[arg-type]


def test_a_node_without_attributes_is_ignored_rather_than_guessed() -> None:
    document = {"type": "doc", "content": [{"type": "citation"}, {"type": "citation", "attrs": {}}]}
    assert collect_citation_nodes(document) == []


def test_a_legacy_free_text_citation_node_is_detected_as_unregistered() -> None:
    """The stage 3 placeholder carried only a free-text key.

    It is reported as unregistered rather than silently turned into a citation, because a
    free-text key is not a reference identifier.
    """
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "citation", "attrs": {"legacyValue": "Auteur2025"}},
                ],
            }
        ],
    }
    assert collect_citation_nodes(document) == []


def test_a_node_with_an_empty_reference_list_is_collected_but_unusable() -> None:
    document = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [citation_node("n1", [])]}],
    }
    nodes = collect_citation_nodes(document)
    assert nodes[0]["reference_ids"] == []


def test_the_narrative_mode_survives_the_json_round_trip() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [citation_node("n1", ["a"], mode="narrative")]},
        ],
    }
    assert collect_citation_nodes(document)[0]["mode"] == "narrative"


def test_the_citation_json_carries_the_identity_not_the_text() -> None:
    """The node must be serialisable and must not carry the rendered string as truth."""
    node = citation_node("n1", ["ref-1"])
    assert set(node["attrs"]) >= {"citationId", "referenceIds"}
    assert "text" not in node["attrs"]


# ---------------------------------------------------------- reference mapping


def make_reference(**overrides) -> BibliographicReference:  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid4(),
        "project_id": uuid4(),
        "citation_key": "dupont2024",
        "reference_type": "article",
        "title": "Composition du grain",
        "publication_year": 2024,
        "journal": "Revue Agro",
        "volume": "10",
        "issue": "2",
        "pages": "10-20",
        "publisher": None,
        "publisher_place": None,
        "edition": None,
        "doi": "10.1234/x",
        "url": None,
        "isbn": None,
        "issn": None,
        "language": None,
        "accessed_at": None,
    }
    defaults.update(overrides)
    return BibliographicReference(**defaults)  # type: ignore[arg-type]


def make_author(**overrides) -> ReferenceAuthor:  # type: ignore[no-untyped-def]
    defaults = {
        "id": uuid4(),
        "reference_id": uuid4(),
        "position": 1,
        "given_name": "Jean",
        "family_name": "Dupont",
        "orcid": None,
        "is_organization": False,
    }
    defaults.update(overrides)
    return ReferenceAuthor(**defaults)  # type: ignore[arg-type]


def test_to_reference_data_preserves_the_author_order_of_stage_9() -> None:
    reference = make_reference()
    authors = [
        make_author(position=1, given_name="Jean", family_name="Dupont"),
        make_author(position=2, given_name="Marie", family_name="Rakoto"),
        make_author(position=3, given_name="Paul", family_name="Martin"),
    ]
    data = to_reference_data(reference, authors)
    assert [author.family_name for author in data.authors] == ["Dupont", "Rakoto", "Martin"]


def test_to_reference_data_keeps_a_missing_year_as_none() -> None:
    data = to_reference_data(make_reference(publication_year=None), [])
    assert data.publication_year is None
    assert data.year_label is None


def test_to_reference_data_carries_the_organisation_flag() -> None:
    author = make_author(given_name=None, family_name="FAO", is_organization=True)
    data = to_reference_data(make_reference(), [author])
    assert data.authors[0].is_organization is True


def test_a_reference_with_no_metadata_still_produces_usable_data() -> None:
    data = to_reference_data(make_reference(title=None, publication_year=None, doi=None), [])
    assert data.has_authors is False
    assert data.title is None


# -------------------------------------------------------------- style default


def test_the_project_style_is_read_and_normalised() -> None:
    """The stored column value is honoured, and a legacy value still resolves."""
    assert inspect.iscoroutinefunction(resolve_project_style)
    source = inspect.getsource(resolve_project_style)
    normalised = source.replace("project.bibliography_style", "Project.bibliography_style")
    assert "Project.bibliography_style" in normalised
    assert "normalise_style_name" in source


def test_an_unknown_project_style_renders_as_apa7() -> None:
    assert get_style("unstyle").name == DEFAULT_STYLE


# ------------------------------------------------------------------ contracts


def test_a_citation_needs_at_least_one_reference() -> None:
    with pytest.raises(ValueError):
        CitationCreateRequest(
            section_id=uuid4(), node_id="n1", items=[]
        )


def test_the_number_of_references_per_citation_is_bounded() -> None:
    with pytest.raises(ValueError):
        CitationCreateRequest(
            section_id=uuid4(),
            node_id="n1",
            items=[
                CitationItemInput(reference_id=uuid4())
                for _ in range(MAX_REFERENCES_PER_CITATION + 1)
            ],
        )


def test_the_node_id_is_bounded_and_required() -> None:
    with pytest.raises(ValueError):
        CitationCreateRequest(
            section_id=uuid4(), node_id="", items=[CitationItemInput(reference_id=uuid4())]
        )
    with pytest.raises(ValueError):
        CitationCreateRequest(
            section_id=uuid4(), node_id="x" * 121, items=[CitationItemInput(reference_id=uuid4())]
        )


def test_an_oversized_locator_is_rejected() -> None:
    with pytest.raises(ValueError):
        CitationItemInput(reference_id=uuid4(), locator_value="9" * 121)


def test_blank_affixes_become_none_instead_of_empty_strings() -> None:
    item = CitationItemInput(reference_id=uuid4(), prefix="  ", suffix="", locator_value=" ")
    assert item.prefix is None
    assert item.suffix is None
    assert item.locator_value is None


def test_an_update_only_reports_the_fields_it_carries() -> None:
    payload = CitationUpdateRequest(suffix=", p. 25")
    assert set(payload.model_dump(exclude_unset=True)) == {"suffix"}


def test_a_preview_needs_at_least_one_reference() -> None:
    with pytest.raises(ValueError):
        PreviewRequest(items=[])


def test_the_locator_type_is_restricted_to_the_documented_set() -> None:
    for value in ("page", "pages", "chapter", "figure", "table", "section", "other"):
        assert CitationItemInput(reference_id=uuid4(), locator_type=value).locator_type == value
    with pytest.raises(ValueError):
        CitationItemInput(reference_id=uuid4(), locator_type="line")


# --------------------------------------------------------- service invariants


def test_a_reference_of_another_project_is_a_404_not_a_message() -> None:
    """Cross-project probing must be indistinguishable from a missing row."""
    source = inspect.getsource(service._validate_references)
    assert "status_code=404" in source
    assert "reference.project_id != project_id" in source


def test_the_service_stores_no_rendered_text_for_the_current_document() -> None:
    """The rendered string must be produced on demand, never persisted as truth."""
    columns = set(BibliographicReference.__table__.columns.keys())
    assert "rendered_text" not in columns
    source = inspect.getsource(service)
    # The only place a rendered text is written is the historical snapshot.
    assert "snapshot_text" in source
    assert source.count("snapshot_text = ") <= 3


def test_deleting_a_citation_never_deletes_a_reference() -> None:
    source = inspect.getsource(service.soft_delete_citation)
    assert "BibliographicReference" not in source
    assert "delete(" not in source


def test_orphans_are_computed_from_live_rows_not_from_a_cached_flag() -> None:
    source = inspect.getsource(service._is_orphaned)
    assert "item.reference_id not in references" in source


def test_the_bibliography_only_contains_cited_references() -> None:
    source = inspect.getsource(service.rendered_bibliography)
    assert "uncited_references" in source
    assert "orphaned_citations" in source


def test_a_reference_cited_twice_appears_once_in_the_bibliography() -> None:
    source = inspect.getsource(service.rendered_bibliography)
    # unique_ids is de-duplicated, and the entries are built from it.
    assert "list(dict.fromkeys(reference_ids))" in source
    assert "cited_data = [" in source


def test_reconciliation_is_idempotent() -> None:
    """Registering the same node twice must update the row, not create a second one."""
    source = inspect.getsource(service.upsert_citation)
    assert "get_citation_by_node" in source
    assert "uq_citations_node_id" not in source  # the constraint lives in the migration


def test_reconcile_does_not_invent_a_reference_for_a_legacy_node() -> None:
    source = inspect.getsource(service.reconcile_section)
    assert "unregistered.append" in source
    assert "if not reference_ids" in source


def test_malformed_reference_identifiers_are_dropped_not_guessed() -> None:
    assert service._parse_reference_ids(["not-a-uuid", "also bad"]) == []
    valid = uuid4()
    assert service._parse_reference_ids([str(valid), "nope", str(valid)]) == [valid]


# ------------------------------------------------------------ route wiring


def _role_requirement(router, method: str, suffix: str) -> str:
    from fastapi.routing import APIRoute

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if method not in route.methods or not route.path.endswith(suffix):
            continue
        for dependency in route.dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name.startswith("require_project_"):
                return name
        return "aucune"
    raise AssertionError(f"Route introuvable : {method} {suffix}")


@pytest.mark.parametrize(
    ("method", "suffix", "expected"),
    [
        ("GET", "/citations", "require_project_reader"),
        ("GET", "/citations/styles", "require_project_reader"),
        ("GET", "/citations/rendered", "require_project_reader"),
        ("POST", "/citations/preview", "require_project_reader"),
        ("GET", "/citations/{citation_id}", "require_project_reader"),
        ("POST", "/citations", "require_project_editor"),
        ("PATCH", "/citations/{citation_id}", "require_project_editor"),
        ("POST", "/citations/reconcile", "require_project_editor"),
        ("POST", "/citations/{citation_id}/detach-reference", "require_project_editor"),
        ("DELETE", "/citations/{citation_id}", "require_project_owner"),
    ],
)
def test_each_citation_route_requires_the_expected_role(
    method: str, suffix: str, expected: str
) -> None:
    from app.citations.router import router

    assert _role_requirement(router, method, suffix) == expected


def test_the_two_bibliography_routes_keep_the_stage_9_roles() -> None:
    from app.bibliography.router import router

    assert (
        _role_requirement(router, "GET", "/bibliography/rendered")
        == "require_project_reader"
    )
    assert (
        _role_requirement(router, "POST", "/bibliography/refresh")
        == "require_project_editor"
    )


def test_every_citation_mutation_requires_csrf() -> None:
    from fastapi.routing import APIRoute

    from app.citations.router import router

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


def test_a_preview_never_reports_a_missing_number_as_if_it_were_known() -> None:
    """The preview route must not fall back to a fabricated number."""
    from app.citations.router import preview_endpoint

    source = inspect.getsource(preview_endpoint)
    assert "Référence introuvable" in source


# ------------------------------------- stage 8 invariant, still enforced in stage 10


def test_the_writing_pipeline_still_exposes_no_section_write() -> None:
    """Stage 10 must not hand the writing assistant a way to write into the memoir."""
    from app.writing import pipeline

    writable = [
        name
        for name in dir(pipeline)
        if callable(getattr(pipeline, name))
        and ("write" in name or "section" in name or "save" in name)
        and not name.startswith("_")
    ]
    assert writable == []


def test_the_writing_actions_forbid_producing_a_citation_or_a_reference() -> None:
    """The model proposes prose; a citation stays under the author's control."""
    from app.writing.actions import SPECS, system_prompt

    prompts = " ".join(system_prompt(action) for action in SPECS).casefold()
    assert prompts
    # The only markers the assistant may emit are the RAG provenance markers of stage 7
    # ("[CITATION:SRC-xxx]"); a bibliographic citation is explicitly forbidden.
    assert "[citation:src-" in prompts
    # The absolute rule of stage 8 still forbids inventing a citation or a reference, and the
    # assistant still writes nothing into the memoir by itself.
    assert "tu n'inventes jamais un auteur, une annee, un doi" in prompts
    assert "une citation ni une reference bibliographique" in prompts
    assert "tu n'ecris jamais directement dans le memoire" in prompts


def test_the_rag_citations_and_the_academic_citations_are_separate_tables() -> None:
    """RAG provenance and academic citation must not be conflated."""
    from app.models.assistant import AssistantCitation
    from app.models.citation import Citation, CitationItem

    assert AssistantCitation.__tablename__ == "assistant_citations"
    assert Citation.__tablename__ == "citations"
    assert CitationItem.__tablename__ == "citation_items"
    # The academic citation points at the bibliography; the RAG citation does not.
    assert "reference_id" in CitationItem.__table__.columns
    assert "reference_id" not in AssistantCitation.__table__.columns


def test_an_academic_citation_never_references_a_rag_chunk() -> None:
    from app.models.citation import CitationItem

    columns = set(CitationItem.__table__.columns.keys())
    assert "chunk_id" not in columns
    assert "document_id" not in columns
