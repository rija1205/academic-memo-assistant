"""Retrieval layer: filters, semantic search, lexical search, fusion, reranking.

Every query is constrained by ``project_id`` at the SQL level, so a result from another
project can never be returned even if a caller tampers with an identifier.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import RagChunk
from app.models.source import Source, SourceFile, SourceTag
from app.rag.settings import (
    FUSION_NORMALIZED,
    FUSION_RRF,
    STRATEGY_HYBRID,
    STRATEGY_LEXICAL,
    STRATEGY_SEMANTIC,
    RagTuning,
)


@dataclass(frozen=True, slots=True)
class RagFilters:
    """Filters accepted by the search API, always combined with the project scope."""

    source_ids: tuple[UUID, ...] = ()
    publication_types: tuple[str, ...] = ()
    year_from: int | None = None
    year_to: int | None = None
    authors: tuple[str, ...] = ()
    page_from: int | None = None
    page_to: int | None = None
    folder_ids: tuple[UUID, ...] = ()
    tags: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not any(
            (
                self.source_ids,
                self.publication_types,
                self.year_from,
                self.year_to,
                self.authors,
                self.page_from,
                self.page_to,
                self.folder_ids,
                self.tags,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_ids": [str(value) for value in self.source_ids],
            "publication_types": list(self.publication_types),
            "year_from": self.year_from,
            "year_to": self.year_to,
            "authors": list(self.authors),
            "page_from": self.page_from,
            "page_to": self.page_to,
            "folder_ids": [str(value) for value in self.folder_ids],
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Academic identity of the source a chunk belongs to."""

    id: UUID
    original_filename: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    publication_year: int | None = None
    publication_type: str = "other"
    journal: str | None = None
    doi: str | None = None
    folder_id: UUID | None = None
    tags: tuple[str, ...] = ()
    file_id: UUID | None = None
    mime_type: str | None = None
    page_count: int | None = None

    def display_title(self) -> str:
        return self.title or self.original_filename


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A retrieved chunk with its score and complete provenance chain."""

    chunk_id: UUID
    rag_document_id: UUID
    project_id: UUID
    source: SourceDescriptor
    text: str
    page_number: int
    block_start: int
    block_end: int
    chunk_index: int
    token_count: int
    provenance_id: UUID
    score: float = 0.0
    vector_score: float | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    lexical_rank: int | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    results: list[ScoredChunk]
    strategy: str
    fusion_method: str | None
    total_candidates: int
    duration_ms: int
    vector_hit_count: int
    lexical_hit_count: int

    @property
    def result_count(self) -> int:
        return len(self.results)


# ------------------------------------------------------------------ filter conditions


def build_filter_conditions(*, project_id: UUID, filters: RagFilters) -> list[Any]:
    """SQL conditions enforcing the project scope and the academic filters.

    The first condition, ``rag_chunks.project_id = :project_id``, is unconditional. It is the
    isolation guarantee of the whole RAG layer.
    """
    conditions: list[Any] = [RagChunk.project_id == project_id]
    if filters.source_ids:
        conditions.append(RagChunk.source_id.in_(filters.source_ids))
    if filters.publication_types:
        conditions.append(Source.publication_type.in_(filters.publication_types))
    if filters.year_from is not None:
        conditions.append(Source.publication_year >= filters.year_from)
    if filters.year_to is not None:
        conditions.append(Source.publication_year <= filters.year_to)
    if filters.page_from is not None:
        conditions.append(RagChunk.page_number >= filters.page_from)
    if filters.page_to is not None:
        conditions.append(RagChunk.page_number <= filters.page_to)
    if filters.folder_ids:
        conditions.append(Source.folder_id.in_(filters.folder_ids))
    if filters.tags:
        normalized = [tag.strip().casefold() for tag in filters.tags if tag.strip()]
        if normalized:
            conditions.append(
                Source.id.in_(
                    select(SourceTag.source_id).where(
                        SourceTag.normalized_name.in_(normalized)
                    )
                )
            )
    if filters.authors:
        patterns = [
            f"%{author.strip().casefold()}%"
            for author in filters.authors
            if author.strip()
        ]
        if patterns:
            conditions.append(
                or_(*[cast(Source.authors, String).ilike(pattern) for pattern in patterns])
            )
    return conditions


_CHUNK_COLUMNS = (
    RagChunk.id.label("chunk_id"),
    RagChunk.rag_document_id,
    RagChunk.project_id,
    RagChunk.source_id,
    RagChunk.provenance_id,
    RagChunk.text,
    RagChunk.page_number,
    RagChunk.block_start,
    RagChunk.block_end,
    RagChunk.chunk_index,
    RagChunk.token_count,
    RagChunk.metadata_json,
    Source.title,
    Source.original_filename,
    Source.authors,
    Source.publication_year,
    Source.publication_type,
    Source.journal,
    Source.doi,
    Source.folder_id,
    Source.page_count,
    SourceFile.id.label("source_file_id"),
    SourceFile.mime_type,
)


def _base_statement(project_id: UUID, filters: RagFilters) -> Select[Any]:
    return (
        select(*_CHUNK_COLUMNS)
        .join(Source, Source.id == RagChunk.source_id)
        .outerjoin(SourceFile, SourceFile.id == RagChunk.source_file_id)
        .where(*build_filter_conditions(project_id=project_id, filters=filters))
    )


async def _tags_by_source(db: AsyncSession, source_ids: list[UUID]) -> dict[UUID, tuple[str, ...]]:
    if not source_ids:
        return {}
    result = await db.execute(
        select(SourceTag.source_id, SourceTag.name).where(SourceTag.source_id.in_(source_ids))
    )
    mapping: dict[UUID, list[str]] = {}
    for source_id, name in result.all():
        mapping.setdefault(source_id, []).append(name)
    return {key: tuple(value) for key, value in mapping.items()}


def _row_to_scored(
    row: Any, *, tags: dict[UUID, tuple[str, ...]]
) -> ScoredChunk:
    descriptor = SourceDescriptor(
        id=row.source_id,
        original_filename=row.original_filename,
        title=row.title,
        authors=tuple(row.authors or ()),
        publication_year=row.publication_year,
        publication_type=row.publication_type or "other",
        journal=row.journal,
        doi=row.doi,
        folder_id=row.folder_id,
        tags=tags.get(row.source_id, ()),
        file_id=row.source_file_id,
        mime_type=row.mime_type,
        page_count=row.page_count,
    )
    return ScoredChunk(
        chunk_id=row.chunk_id,
        rag_document_id=row.rag_document_id,
        project_id=row.project_id,
        source=descriptor,
        text=row.text,
        page_number=row.page_number,
        block_start=row.block_start,
        block_end=row.block_end,
        chunk_index=row.chunk_index,
        token_count=row.token_count,
        provenance_id=row.provenance_id,
        metadata=dict(row.metadata_json or {}),
    )


async def _materialize(
    db: AsyncSession, rows: list[Any]
) -> list[tuple[Any, dict[UUID, tuple[str, ...]]]]:
    tags = await _tags_by_source(db, [row.source_id for row in rows])
    return [(row, tags) for row in rows]


# -------------------------------------------------------------------- semantic search


async def semantic_search(
    db: AsyncSession,
    *,
    project_id: UUID,
    query_embedding: list[float],
    top_k: int,
    filters: RagFilters | None = None,
) -> list[ScoredChunk]:
    """Vector retrieval constrained to one project, served by the pgvector HNSW index.

    Similarity is the cosine distance exposed by pgvector: ``1 - (embedding <=> query)``.
    """
    effective = filters or RagFilters()
    similarity = 1.0 - RagChunk.embedding.cosine_distance(query_embedding)
    statement = (
        _base_statement(project_id, effective)
        .add_columns(similarity.label("similarity"))
        .where(RagChunk.embedding.is_not(None))
        .order_by(RagChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    rows = list((await db.execute(statement)).all())
    results: list[ScoredChunk] = []
    for rank, (row, tags) in enumerate(await _materialize(db, rows), start=1):
        value = float(row.similarity)
        results.append(
            replace(
                _row_to_scored(row, tags=tags),
                score=value,
                vector_score=value,
                vector_rank=rank,
            )
        )
    return results


# --------------------------------------------------------------------- lexical search


async def lexical_search(
    db: AsyncSession,
    *,
    project_id: UUID,
    query: str,
    top_k: int,
    filters: RagFilters | None = None,
    text_search_config: str = "simple",
) -> list[ScoredChunk]:
    """Full-text and trigram retrieval, functional without any embedding.

    Two complementary PostgreSQL capabilities are combined:

    * ``ts_rank_cd`` over a ``tsvector`` built with the configured text search config, which
      handles terms, phrases and ranking;
    * ``similarity()`` from ``pg_trgm``, which keeps partial and misspelled terms reachable.
    """
    effective = filters or RagFilters()
    tsvector = func.to_tsvector(text_search_config, RagChunk.text)
    tsquery = func.websearch_to_tsquery(text_search_config, query)
    rank = func.ts_rank_cd(tsvector, tsquery)
    trigram = func.similarity(RagChunk.text, query)
    statement = (
        _base_statement(project_id, effective)
        .add_columns(rank.label("ts_rank"), trigram.label("trigram"))
        .where(tsvector.op("@@")(tsquery))
        .order_by((rank + trigram).desc())
        .limit(top_k)
    )
    rows = list((await db.execute(statement)).all())
    results: list[ScoredChunk] = []
    for position, (row, tags) in enumerate(await _materialize(db, rows), start=1):
        combined = float(row.ts_rank) + float(row.trigram)
        results.append(
            replace(
                _row_to_scored(row, tags=tags),
                score=combined,
                lexical_score=combined,
                lexical_rank=position,
            )
        )
    return results


# ---------------------------------------------------------------------------- fusion


def reciprocal_rank_fusion(
    *,
    vector_results: list[ScoredChunk],
    lexical_results: list[ScoredChunk],
    k: int = 60,
    weight_vector: float = 1.0,
    weight_lexical: float = 1.0,
    top_k: int = 10,
) -> list[ScoredChunk]:
    """Fuse two ranked lists with Reciprocal Rank Fusion.

    RRF compares positions rather than raw scores, which is exactly what is required when a
    cosine distance and a ``ts_rank`` live on different scales. The fused score of a chunk is
    ``sum(weight / (k + rank))`` over every list that contains it.
    """
    if k <= 0:
        raise ValueError("RRF k must be positive")
    merged: dict[UUID, ScoredChunk] = {}
    contributions: dict[UUID, float] = {}

    for weight, results, is_vector in (
        (weight_vector, vector_results, True),
        (weight_lexical, lexical_results, False),
    ):
        if weight <= 0:
            continue
        for rank, chunk in enumerate(results, start=1):
            contributions[chunk.chunk_id] = (
                contributions.get(chunk.chunk_id, 0.0) + weight / (k + rank)
            )
            score = chunk.vector_score if is_vector else chunk.lexical_score
            merged[chunk.chunk_id] = replace(
                merged.get(chunk.chunk_id, chunk),
                **(
                    {"vector_score": score if score is not None else chunk.score,
                     "vector_rank": rank}
                    if is_vector
                    else {"lexical_score": score if score is not None else chunk.score,
                          "lexical_rank": rank}
                ),
            )

    ordered = sorted(
        merged.values(),
        key=lambda chunk: (-contributions[chunk.chunk_id], chunk.chunk_id.hex),
    )
    return [
        replace(chunk, score=round(contributions[chunk.chunk_id], 6))
        for chunk in ordered[:top_k]
    ]


def normalized_score_fusion(
    *,
    vector_results: list[ScoredChunk],
    lexical_results: list[ScoredChunk],
    weight_vector: float = 1.0,
    weight_lexical: float = 1.0,
    top_k: int = 10,
) -> list[ScoredChunk]:
    """Fuse two lists after min-max normalising each score range to [0, 1]."""
    vector_normalized = _min_max(vector_results)
    lexical_normalized = _min_max(lexical_results)
    merged: dict[UUID, ScoredChunk] = {}
    scores: dict[UUID, float] = {}

    for weight, normalized, is_vector in (
        (weight_vector, vector_normalized, True),
        (weight_lexical, lexical_normalized, False),
    ):
        if weight <= 0:
            continue
        for chunk, value in normalized:
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + weight * value
            merged[chunk.chunk_id] = replace(
                merged.get(chunk.chunk_id, chunk),
                **(
                    {"vector_score": chunk.vector_score or chunk.score}
                    if is_vector
                    else {"lexical_score": chunk.lexical_score or chunk.score}
                ),
            )

    ordered = sorted(
        merged.values(),
        key=lambda chunk: (-scores[chunk.chunk_id], chunk.chunk_id.hex),
    )
    return [replace(chunk, score=round(scores[chunk.chunk_id], 6)) for chunk in ordered[:top_k]]


def _min_max(results: list[ScoredChunk]) -> list[tuple[ScoredChunk, float]]:
    if not results:
        return []
    values = [
        float(chunk.vector_score if chunk.vector_score is not None else chunk.score)
        if chunk.vector_score is not None
        else float(chunk.lexical_score if chunk.lexical_score is not None else chunk.score)
        for chunk in results
    ]
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        constant = 1.0 if high > 0 else 0.0
        return [(chunk, constant) for chunk in results]
    return [(chunk, (value - low) / span) for chunk, value in zip(results, values, strict=True)]


# ------------------------------------------------------------------------- reranking


class RerankerProvider:
    """Optional reranking stage. Retrieval behaves identically when none is configured."""

    name = "none"

    def rerank(
        self, *, query: str, results: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        return results[:top_k]


class LexicalOverlapReranker(RerankerProvider):
    """Deterministic reranker based on query-term coverage.

    Fully explainable and offline: no neural model, no network. It promotes passages that
    actually contain the query terms over passages retrieved only by embedding similarity.
    """

    name = "mock"

    def __init__(self, *, model: str = "lexical-overlap") -> None:
        self.model = model

    def rerank(
        self, *, query: str, results: list[ScoredChunk], top_k: int
    ) -> list[ScoredChunk]:
        terms = {term.strip(".,;:!?()[]\"'") for term in query.casefold().split()}
        terms = {term for term in terms if len(term) > 1}
        if not terms:
            return results[:top_k]
        reranked: list[tuple[float, ScoredChunk]] = []
        for chunk in results:
            tokens = {token.strip(".,;:!?()[]\"'") for token in chunk.text.casefold().split()}
            coverage = len(terms & tokens) / len(terms) if terms else 0.0
            # Base relevance keeps 75% of the weight so reranking never fully discards a
            # passage that the retriever considered relevant.
            value = 0.75 * chunk.score + 0.25 * coverage
            reranked.append(
                (
                    value,
                    replace(
                        chunk,
                        score=round(value, 6),
                        rerank_score=round(coverage, 6),
                    ),
                )
            )
        reranked.sort(key=lambda item: (-item[0], item[1].chunk_id.hex))
        return [chunk for _, chunk in reranked[:top_k]]


def build_reranker(settings: Any) -> RerankerProvider:
    provider = getattr(settings, "reranker_provider", "none")
    if provider == "mock":
        return LexicalOverlapReranker(
            model=getattr(settings, "reranker_model", "") or "lexical-overlap"
        )
    return RerankerProvider()


# ----------------------------------------------------------------------- orchestration


async def hybrid_search(
    db: AsyncSession,
    *,
    project_id: UUID,
    query: str,
    query_embedding: list[float] | None,
    top_k: int,
    tuning: RagTuning,
    filters: RagFilters | None = None,
    strategy: str | None = None,
    fusion_method: str | None = None,
    reranker: RerankerProvider | None = None,
) -> SearchOutcome:
    """Run the requested strategy and return fused, reranked passages.

    * ``semantic``: pgvector only;
    * ``lexical``: full-text only, no embedding required;
    * ``hybrid``: both, fused with RRF (default) or normalised scores.
    """
    started = time.perf_counter()
    effective_strategy = strategy or tuning.strategy
    effective_fusion = fusion_method or tuning.fusion_method
    candidates = max(top_k * tuning.candidate_multiplier, top_k)

    vector_results: list[ScoredChunk] = []
    lexical_results: list[ScoredChunk] = []

    if effective_strategy in {STRATEGY_SEMANTIC, STRATEGY_HYBRID}:
        if query_embedding is None:
            if effective_strategy == STRATEGY_SEMANTIC:
                raise ValueError("La recherche sémantique requiert un embedding de requête.")
        else:
            vector_results = await semantic_search(
                db,
                project_id=project_id,
                query_embedding=query_embedding,
                top_k=candidates,
                filters=filters,
            )

    if effective_strategy in {STRATEGY_LEXICAL, STRATEGY_HYBRID}:
        lexical_results = await lexical_search(
            db,
            project_id=project_id,
            query=query,
            top_k=candidates,
            filters=filters,
            text_search_config=tuning.text_search_config,
        )

    if effective_strategy == STRATEGY_SEMANTIC:
        fused = vector_results[:top_k]
    elif effective_strategy == STRATEGY_LEXICAL:
        fused = lexical_results[:top_k]
    elif effective_fusion == FUSION_NORMALIZED:
        fused = normalized_score_fusion(
            vector_results=vector_results,
            lexical_results=lexical_results,
            weight_vector=tuning.rrf_weight_vector,
            weight_lexical=tuning.rrf_weight_lexical,
            top_k=candidates,
        )
    elif effective_fusion == FUSION_RRF:
        fused = reciprocal_rank_fusion(
            vector_results=vector_results,
            lexical_results=lexical_results,
            k=tuning.rrf_k,
            weight_vector=tuning.rrf_weight_vector,
            weight_lexical=tuning.rrf_weight_lexical,
            top_k=candidates,
        )
    else:
        raise ValueError(f"Méthode de fusion inconnue : {effective_fusion}")

    final = (reranker or RerankerProvider()).rerank(query=query, results=fused, top_k=top_k)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return SearchOutcome(
        results=final,
        strategy=effective_strategy,
        fusion_method=effective_fusion if effective_strategy == STRATEGY_HYBRID else None,
        total_candidates=max(len(vector_results), len(lexical_results)),
        duration_ms=duration_ms,
        vector_hit_count=len(vector_results),
        lexical_hit_count=len(lexical_results),
    )
