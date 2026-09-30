"""Unit tests for retrieval fusion, reranking, filters and provenance.

These tests run without PostgreSQL: they exercise the pure retrieval logic that decides how
candidate passages are combined and ranked. The SQL isolation guarantee is covered by the
integration tests, which assert that the project condition is always present.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.rag.provenance import build_provenance, build_source_summary
from app.rag.search.retrieval import (
    LexicalOverlapReranker,
    RagFilters,
    RerankerProvider,
    ScoredChunk,
    SourceDescriptor,
    build_filter_conditions,
    build_reranker,
    normalized_score_fusion,
    reciprocal_rank_fusion,
)

PROJECT_ID = uuid4()
OTHER_PROJECT_ID = uuid4()


def make_chunk(
    *,
    text: str,
    page: int = 1,
    source_id: UUID | None = None,
    score: float = 0.5,
    vector_score: float | None = None,
    lexical_score: float | None = None,
    vector_rank: int | None = None,
    lexical_rank: int | None = None,
    block_start: int = 0,
    block_end: int = 0,
    metadata: dict | None = None,
) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=uuid4(),
        rag_document_id=uuid4(),
        project_id=PROJECT_ID,
        source=SourceDescriptor(
            id=source_id or uuid4(),
            original_filename="article.pdf",
            title="Le grain de jacquier",
            authors=("Nkolo",),
            publication_year=2024,
            file_id=uuid4(),
        ),
        text=text,
        page_number=page,
        block_start=block_start,
        block_end=block_end,
        chunk_index=0,
        token_count=10,
        provenance_id=uuid4(),
        score=score,
        vector_score=vector_score,
        lexical_score=lexical_score,
        vector_rank=vector_rank,
        lexical_rank=lexical_rank,
        metadata=metadata or {},
    )


# ------------------------------------------------------------------ reciprocal rank fusion


def test_rrf_ranks_a_chunk_present_in_both_lists_first() -> None:
    shared = make_chunk(text="jacquier", score=0.9)
    only_vector = make_chunk(text="fibres", score=0.8)
    only_lexical = make_chunk(text="proteines", score=0.7)
    fused = reciprocal_rank_fusion(
        vector_results=[shared, only_vector],
        lexical_results=[shared, only_lexical],
        k=60,
        top_k=10,
    )
    assert fused[0].chunk_id == shared.chunk_id
    assert len(fused) == 3


def test_rrf_is_not_a_plain_concatenation() -> None:
    """A chunk ranked last by one list can still beat a chunk ranked first by that list."""
    vector_first = make_chunk(text="A", score=0.99)
    also_in_lexical = make_chunk(text="B", score=0.01)
    lexical_first = make_chunk(text="C", score=0.99)
    fused = reciprocal_rank_fusion(
        vector_results=[vector_first, also_in_lexical],
        lexical_results=[lexical_first, also_in_lexical],
        k=60,
        top_k=10,
    )
    positions = {chunk.chunk_id: index for index, chunk in enumerate(fused)}
    assert positions[also_in_lexical.chunk_id] < positions[lexical_first.chunk_id]


def test_rrf_score_matches_the_formula() -> None:
    chunk = make_chunk(text="x")
    fused = reciprocal_rank_fusion(
        vector_results=[chunk], lexical_results=[], k=60, top_k=5
    )
    assert fused[0].score == round(1.0 / 61, 6)


def test_rrf_weights_change_the_ranking() -> None:
    vector_strong = make_chunk(text="V")
    lexical_strong = make_chunk(text="L")
    balanced = reciprocal_rank_fusion(
        vector_results=[vector_strong],
        lexical_results=[lexical_strong],
        weight_vector=1.0,
        weight_lexical=1.0,
        top_k=5,
    )
    # Equal weights tie: both contributions are 1/(k+1).
    assert balanced[0].score == balanced[1].score == round(1.0 / 61, 6)

    vector_favoured = reciprocal_rank_fusion(
        vector_results=[vector_strong],
        lexical_results=[lexical_strong],
        weight_vector=5.0,
        weight_lexical=1.0,
        top_k=5,
    )
    assert vector_favoured[0].chunk_id == vector_strong.chunk_id
    assert vector_favoured[0].score == round(5.0 / 61, 6)
    assert vector_favoured[0].score > balanced[0].score


def test_rrf_respects_top_k_and_rejects_invalid_k() -> None:
    chunks = [make_chunk(text=f"chunk {index}") for index in range(5)]
    fused = reciprocal_rank_fusion(vector_results=chunks, lexical_results=[], k=60, top_k=2)
    assert len(fused) == 2
    try:
        reciprocal_rank_fusion(vector_results=chunks, lexical_results=[], k=0, top_k=2)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("k must be validated")


def test_rrf_ignores_a_list_with_zero_weight() -> None:
    only_vector = make_chunk(text="V")
    fused = reciprocal_rank_fusion(
        vector_results=[only_vector],
        lexical_results=[make_chunk(text="L")],
        weight_vector=1.0,
        weight_lexical=0.0,
        top_k=5,
    )
    assert [chunk.chunk_id for chunk in fused] == [only_vector.chunk_id]


# -------------------------------------------------------------------- normalized fusion


def test_normalized_fusion_maps_scores_to_unit_interval() -> None:
    best = make_chunk(text="best", score=0.9, vector_score=0.9)
    worst = make_chunk(text="worst", score=0.1, vector_score=0.1)
    fused = normalized_score_fusion(
        vector_results=[best, worst], lexical_results=[], top_k=5
    )
    assert fused[0].chunk_id == best.chunk_id
    assert fused[0].score == 1.0
    assert fused[-1].score == 0.0


def test_normalized_fusion_handles_a_constant_score_range() -> None:
    first = make_chunk(text="a", score=0.5, vector_score=0.5)
    second = make_chunk(text="b", score=0.5, vector_score=0.5)
    fused = normalized_score_fusion(
        vector_results=[first, second], lexical_results=[], top_k=5
    )
    assert all(chunk.score == 1.0 for chunk in fused)


# ------------------------------------------------------------------------ reranking


def test_reranking_promotes_passages_containing_the_query_terms() -> None:
    without_terms = make_chunk(text="Passage sans rapport avec la demande.", score=0.9)
    with_terms = make_chunk(text="Le jacquier contient des fibres.", score=0.6)
    reranked = LexicalOverlapReranker().rerank(
        query="jacquier fibres", results=[without_terms, with_terms], top_k=2
    )
    assert reranked[0].chunk_id == with_terms.chunk_id
    assert reranked[0].rerank_score == 1.0


def test_reranking_is_optional_and_disabled_by_default() -> None:
    chunks = [make_chunk(text="a"), make_chunk(text="b")]
    assert isinstance(build_reranker(_Settings(reranker_provider="none")), RerankerProvider)
    assert build_reranker(_Settings(reranker_provider="none")).rerank(
        query="a", results=chunks, top_k=1
    ) == chunks[:1]


def test_mock_reranker_can_be_enabled() -> None:
    reranker = build_reranker(_Settings(reranker_provider="mock"))
    assert isinstance(reranker, LexicalOverlapReranker)


def test_reranker_without_query_terms_keeps_the_original_order() -> None:
    chunks = [make_chunk(text="a", score=0.9), make_chunk(text="b", score=0.1)]
    assert LexicalOverlapReranker().rerank(query=" ", results=chunks, top_k=2) == chunks


# ----------------------------------------------------------------------------- filters


def test_filter_conditions_always_scope_to_the_project() -> None:
    conditions = build_filter_conditions(project_id=PROJECT_ID, filters=RagFilters())
    assert str(conditions[0]) == "rag_chunks.project_id = :project_id_1"
    rendered = str(conditions[0])
    assert "rag_chunks.project_id" in rendered


def test_filter_conditions_build_every_documented_filter() -> None:
    filters = RagFilters(
        source_ids=(uuid4(),),
        publication_types=("article",),
        year_from=2020,
        year_to=2024,
        authors=("Nkolo",),
        page_from=3,
        page_to=9,
        folder_ids=(uuid4(),),
        tags=("milieu",),
    )
    conditions = build_filter_conditions(project_id=PROJECT_ID, filters=filters)
    # project + source + type + year_from + year_to + page_from + page_to + folder + tags + authors
    assert len(conditions) == 10
    assert not filters.is_empty()


def test_empty_filters_are_detected() -> None:
    assert RagFilters().is_empty()
    assert not RagFilters(tags=("x",)).is_empty()


# ------------------------------------------------------------------------ provenance


def test_provenance_exposes_the_full_chain() -> None:
    source_id = uuid4()
    chunk = make_chunk(
        text="Le grain contient des fibres.",
        page=12,
        source_id=source_id,
        block_start=3,
        block_end=5,
        metadata={
            "heading_path": ["Nutrition", "Fibres"],
            "block_types": ["paragraph"],
            "sentence_split": False,
            "character_start": 120,
            "character_end": 340,
        },
    )
    provenance = build_provenance(chunk, project_id=PROJECT_ID)
    assert provenance.project_id == PROJECT_ID
    assert provenance.source_id == source_id
    assert provenance.source_file_id == chunk.source.file_id
    assert provenance.page_number == 12
    assert provenance.block_start == 3
    assert provenance.block_end == 5
    assert provenance.provenance_id == chunk.provenance_id
    assert provenance.chunk_id == chunk.chunk_id
    assert provenance.heading_path == ["Nutrition", "Fibres"]
    assert provenance.character_start == 120
    assert provenance.source_url.endswith("/preview?page=12")


def test_citation_marker_contains_author_year_and_page() -> None:
    chunk = make_chunk(text="x", page=7)
    marker = build_provenance(chunk, project_id=PROJECT_ID).as_citation_marker()
    assert "Nkolo" in marker
    assert "2024" in marker
    assert "p. 7" in marker


def test_source_summary_is_serialisable() -> None:
    chunk = make_chunk(text="x")
    summary = build_source_summary(chunk)
    assert summary.id == chunk.source.id
    assert summary.authors == ["Nkolo"]
    assert summary.year == 2024


class _Settings:
    def __init__(self, **values: object) -> None:
        self.reranker_provider = values.get("reranker_provider", "none")
        self.reranker_model = values.get("reranker_model", "")
