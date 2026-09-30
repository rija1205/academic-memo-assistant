"""RAG service layer: search orchestration, document listing and statistics."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.rag import RagDocument
from app.models.source import Source
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.rag.pipeline import (
    document_needs_reindex,
    list_queries,
    list_rag_documents,
    rag_project_stats,
    record_query,
)
from app.rag.provenance import build_provenance, build_source_summary
from app.rag.schemas import (
    RagDocumentListResponse,
    RagDocumentResponse,
    RagQueryHistoryListResponse,
    RagQueryHistoryResponse,
    RagSearchFilters,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResult,
    RagStatsResponse,
)
from app.rag.search.retrieval import (
    RagFilters,
    build_reranker,
    hybrid_search,
)
from app.rag.settings import (
    STRATEGY_SEMANTIC,
    RagTuning,
    rag_tuning,
)


def to_domain_filters(filters: RagSearchFilters) -> RagFilters:
    return RagFilters(
        source_ids=tuple(filters.source_ids),
        publication_types=tuple(filters.publication_types),
        year_from=filters.year_from,
        year_to=filters.year_to,
        authors=tuple(filters.authors),
        page_from=filters.page_from,
        page_to=filters.page_to,
        folder_ids=tuple(filters.folder_ids),
        tags=tuple(filters.tags),
    )


async def to_document_response(
    document: RagDocument, *, tuning: RagTuning, db: AsyncSession | None = None
) -> RagDocumentResponse:
    title: str | None = None
    filename = ""
    if db is not None:
        row = await db.execute(
            select(Source.title, Source.original_filename).where(Source.id == document.source_id)
        )
        found = row.one_or_none()
        if found is not None:
            title, filename = found
    if not filename:
        filename = str(document.source_id)
    needs, _ = await document_needs_reindex(document, tuning)
    return RagDocumentResponse(
        id=document.id,
        project_id=document.project_id,
        source_id=document.source_id,
        source_title=title,
        original_filename=filename,
        status=document.status,
        index_signature=document.index_signature,
        embedding_provider=document.embedding_provider,
        embedding_model=document.embedding_model,
        embedding_version=document.embedding_version,
        chunking_version=document.chunking_version,
        embedding_dimension=document.embedding_dimension,
        chunk_count=document.chunk_count,
        token_count=document.token_count,
        estimated_cost_usd=document.estimated_cost_usd,
        page_count=document.page_count,
        error_message=document.error_message,
        attempts=document.attempts,
        indexed_at=document.indexed_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        needs_reindex=needs,
    )


async def perform_search(
    db: AsyncSession,
    *,
    project_id: UUID,
    payload: RagSearchRequest,
    settings: Settings,
) -> RagSearchResponse:
    """Run a retrieval query. No language-model generation happens here."""
    tuning = rag_tuning(settings)
    top_k = min(payload.top_k or settings.rag_default_top_k, settings.rag_max_top_k)
    strategy = payload.strategy or tuning.strategy
    filters = to_domain_filters(payload.filters)

    query_embedding: list[float] | None = None
    if strategy in {STRATEGY_SEMANTIC, "hybrid"}:
        try:
            provider = build_embedding_provider(settings)
        except EmbeddingError as exc:
            # A missing embedding provider must not break the lexical path.
            if strategy == STRATEGY_SEMANTIC:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            provider = None
        if provider is not None:
            try:
                query_embedding = provider.embed_query(payload.query)
            except EmbeddingError as exc:
                if strategy == STRATEGY_SEMANTIC:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                query_embedding = None

    outcome = await hybrid_search(
        db,
        project_id=project_id,
        query=payload.query,
        query_embedding=query_embedding,
        top_k=top_k,
        tuning=tuning,
        filters=filters,
        strategy=strategy,
        fusion_method=payload.fusion_method,
        reranker=build_reranker(settings),
    )

    results = []
    for chunk in outcome.results:
        provenance = build_provenance(chunk, project_id=project_id)
        results.append(
            RagSearchResult(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=round(chunk.score, 6),
                vector_score=chunk.vector_score,
                lexical_score=chunk.lexical_score,
                rerank_score=chunk.rerank_score,
                vector_rank=chunk.vector_rank,
                lexical_rank=chunk.lexical_rank,
                token_count=chunk.token_count,
                source=build_source_summary(chunk),
                page=chunk.page_number,
                provenance=provenance,
                citation_marker=provenance.as_citation_marker(),
            )
        )

    await record_query(
        db,
        project_id=project_id,
        query=payload.query,
        outcome=outcome,
        top_k=top_k,
        filters=filters,
    )

    return RagSearchResponse(
        query=payload.query,
        strategy=outcome.strategy,
        fusion_method=outcome.fusion_method,
        reranker=build_reranker(settings).name,
        top_k=top_k,
        total_candidates=outcome.total_candidates,
        duration_ms=outcome.duration_ms,
        vector_hits=outcome.vector_hit_count,
        lexical_hits=outcome.lexical_hit_count,
        results=results,
    )


async def list_documents(
    db: AsyncSession, *, project_id: UUID, settings: Settings
) -> RagDocumentListResponse:
    tuning = rag_tuning(settings)
    documents = await list_rag_documents(db, project_id=project_id)
    items = [await to_document_response(document, tuning=tuning, db=db) for document in documents]
    return RagDocumentListResponse(items=items, total=len(items))


async def build_stats(
    db: AsyncSession, *, project_id: UUID, settings: Settings
) -> RagStatsResponse:
    tuning = rag_tuning(settings)
    raw = await rag_project_stats(db, project_id=project_id)
    return RagStatsResponse(
        documents_total=int(raw["documents_total"]),
        documents_indexed=int(raw["documents_indexed"]),
        documents_pending=int(raw["documents_pending"]),
        chunks_total=int(raw["chunks_total"]),
        tokens_total=int(raw["tokens_total"]),
        estimated_cost_usd=float(raw["estimated_cost_usd"]),
        embedding_provider=tuning.embedding_provider,
        embedding_model=tuning.embedding_model,
        embedding_dimension=tuning.embedding_dimension,
        embedding_version=tuning.embedding_version,
        chunking_version=tuning.chunking_version,
        chunk_max_tokens=tuning.chunk_max_tokens,
        chunk_overlap_tokens=tuning.chunk_overlap_tokens,
        search_strategy=tuning.strategy,
        fusion_method=tuning.fusion_method,
        reranker=build_reranker(settings).name,
    )


async def get_query_history(
    db: AsyncSession, *, project_id: UUID, limit: int = 50
) -> RagQueryHistoryListResponse:
    entries = await list_queries(db, project_id=project_id, limit=limit)
    return RagQueryHistoryListResponse(
        items=[
            RagQueryHistoryResponse(
                id=entry.id,
                query=entry.query_text,
                strategy=entry.strategy,
                fusion_method=entry.fusion_method,
                top_k=entry.top_k,
                result_count=entry.result_count,
                semantic_hits=entry.semantic_hits,
                lexical_hits=entry.lexical_hits,
                duration_ms=entry.duration_ms,
                created_at=entry.created_at,
            )
            for entry in entries
        ]
    )


async def resolve_source_for_indexing(
    db: AsyncSession, *, project_id: UUID, source_id: UUID
) -> Source:
    result = await db.execute(
        select(Source).where(
            Source.id == source_id,
            Source.project_id == project_id,
            Source.deleted_at.is_(None),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source introuvable dans ce projet.")
    return source
