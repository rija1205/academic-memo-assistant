"""RAG HTTP API.

Permission model, enforced on the backend for every route:

* ``owner``: search, index, reindex, deindex, statistics, history.
* ``editor``: search, index new sources, reindex, deindex, statistics, history.
* ``reader``: search, statistics and history only. Any indexing or deindexing attempt is
  rejected with ``403`` before any work is done.

No route performs language-model generation: this stage only retrieves passages.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_csrf
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.source import Source
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_reader,
)
from app.rag.cost import embedding_cost_report
from app.rag.dispatch import enqueue_rag_deindex, enqueue_rag_index
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.rag.pipeline import IndexingError, deindex_source, index_source
from app.rag.schemas import (
    RagDocumentListResponse,
    RagDocumentResponse,
    RagIndexActionResponse,
    RagQueryHistoryListResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagStatsResponse,
)
from app.rag.service import (
    build_stats,
    get_query_history,
    list_documents,
    perform_search,
    resolve_source_for_indexing,
    to_document_response,
)
from app.rag.settings import rag_tuning
from app.sources.dependencies import require_worker_token

router = APIRouter(prefix="/api", tags=["rag"])


async def _index_source(
    db: AsyncSession,
    *,
    project_id: UUID,
    source_id: UUID,
    force: bool,
    settings: Settings,
) -> RagIndexActionResponse:
    """Shared index action used by both the index and the reindex routes."""
    source = await resolve_source_for_indexing(db, project_id=project_id, source_id=source_id)
    if source.status != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La source doit être traitée avant d'être indexée.",
        )
    tuning = rag_tuning(settings)
    try:
        provider = build_embedding_provider(settings)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if settings.source_processing_mode == "async":
        enqueue_rag_index(source_id=source.id, settings=settings, force=force)
        return RagIndexActionResponse(
            message="Indexation programmée.", document=None, queued=True
        )

    try:
        document = await index_source(
            db, source_id=source.id, provider=provider, tuning=tuning, force=force
        )
    except (IndexingError, EmbeddingError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RagIndexActionResponse(
        message=(
            "Source déjà indexée."
            if document.status == "indexed" and not force
            else "Source indexée."
        ),
        document=await to_document_response(document, tuning=tuning, db=db),
        queued=False,
    )


@router.post(
    "/projects/{project_id}/rag/search",
    response_model=RagSearchResponse,
    summary="Recherche hybride dans les sources du projet",
)
async def search_sources(
    project_id: UUID,
    payload: RagSearchRequest,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RagSearchResponse:
    return await perform_search(db, project_id=project_id, payload=payload, settings=settings)


@router.get(
    "/projects/{project_id}/rag/documents",
    response_model=RagDocumentListResponse,
    summary="État de l'index RAG du projet",
)
async def rag_documents(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RagDocumentListResponse:
    return await list_documents(db, project_id=project_id, settings=settings)


@router.get(
    "/projects/{project_id}/rag/stats",
    response_model=RagStatsResponse,
    summary="Statistiques de l'index et des coûts",
)
async def rag_stats(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RagStatsResponse:
    return await build_stats(db, project_id=project_id, settings=settings)


@router.get(
    "/projects/{project_id}/rag/queries",
    response_model=RagQueryHistoryListResponse,
    summary="Historique technique des recherches",
)
async def rag_query_history(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> RagQueryHistoryListResponse:
    return await get_query_history(db, project_id=project_id, limit=limit)


@router.post(
    "/projects/{project_id}/rag/sources/{source_id}/index",
    response_model=RagIndexActionResponse,
    summary="Indexer une source",
)
async def index_source_route(
    project_id: UUID,
    source_id: UUID,
    force: bool = Query(default=False),
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> RagIndexActionResponse:
    return await _index_source(
        db,
        project_id=project_id,
        source_id=source_id,
        force=force,
        settings=settings,
    )


@router.post(
    "/projects/{project_id}/rag/sources/{source_id}/reindex",
    response_model=RagIndexActionResponse,
    summary="Réindexer explicitement une source",
)
async def reindex_source_route(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> RagIndexActionResponse:
    return await _index_source(
        db,
        project_id=project_id,
        source_id=source_id,
        force=True,
        settings=settings,
    )


@router.post(
    "/projects/{project_id}/rag/sources/{source_id}/deindex",
    response_model=RagIndexActionResponse,
    summary="Désindexer une source sans la supprimer",
)
async def deindex_source_route(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> RagIndexActionResponse:
    await resolve_source_for_indexing(db, project_id=project_id, source_id=source_id)
    tuning = rag_tuning(settings)
    if settings.source_processing_mode == "async":
        enqueue_rag_deindex(source_id=source_id, settings=settings)
        return RagIndexActionResponse(
            message="Désindexation programmée.", document=None, queued=True
        )
    document = await deindex_source(db, source_id=source_id)
    return RagIndexActionResponse(
        message="Source désindexée.",
        document=(
            await to_document_response(document, tuning=tuning, db=db)
            if document is not None
            else None
        ),
        queued=False,
    )


@router.post(
    "/projects/{project_id}/rag/reindex",
    response_model=RagIndexActionResponse,
    summary="Réindexer toutes les sources traitées du projet",
)
async def reindex_project_route(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> RagIndexActionResponse:
    result = await db.execute(
        select(Source).where(
            Source.project_id == project_id,
            Source.deleted_at.is_(None),
            Source.status == "processed",
        )
    )
    sources = list(result.scalars().all())
    tuning = rag_tuning(settings)
    queued = False
    failures = 0
    if settings.source_processing_mode == "async":
        for source in sources:
            enqueue_rag_index(source_id=source.id, settings=settings, force=True)
        queued = bool(sources)
    else:
        try:
            provider = build_embedding_provider(settings)
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        for source in sources:
            try:
                await index_source(
                    db, source_id=source.id, provider=provider, tuning=tuning, force=True
                )
            except (IndexingError, EmbeddingError):
                failures += 1
    verb = "programmée(s)" if queued else "réindexée(s)"
    suffix = f" ({failures} en échec)" if failures else ""
    return RagIndexActionResponse(
        message=f"{len(sources)} source(s) {verb}.{suffix}",
        document=None,
        queued=queued,
    )


@router.post(
    "/internal/rag/sources/{source_id}/index",
    response_model=RagDocumentResponse,
    summary="Indexation interne déclenchée par le worker",
)
async def internal_index_source(
    source_id: UUID,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_worker_token),
) -> RagDocumentResponse:
    try:
        provider = build_embedding_provider(settings)
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        document = await index_source(
            db,
            source_id=source_id,
            provider=provider,
            tuning=rag_tuning(settings),
            force=force,
        )
    except (IndexingError, EmbeddingError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await to_document_response(document, tuning=rag_tuning(settings), db=db)


@router.post(
    "/internal/rag/sources/{source_id}/deindex",
    response_model=RagDocumentResponse,
    summary="Désindexation interne déclenchée par le worker",
)
async def internal_deindex_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_worker_token),
) -> RagDocumentResponse:
    document = await deindex_source(db, source_id=source_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Aucun index pour cette source.")
    return await to_document_response(document, tuning=rag_tuning(settings), db=db)


@router.get("/internal/rag/config", summary="Configuration RAG effective (sans secret)")
async def internal_rag_config(
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_worker_token),
) -> Response:
    tuning = rag_tuning(settings)
    payload = {
        "embedding_provider": tuning.embedding_provider,
        "embedding_model": tuning.embedding_model,
        "embedding_dimension": tuning.embedding_dimension,
        "embedding_version": tuning.embedding_version,
        "chunking_version": tuning.chunking_version,
        "chunk_max_tokens": tuning.chunk_max_tokens,
        "chunk_overlap_tokens": tuning.chunk_overlap_tokens,
        "index_signature": tuning.index_signature,
        "cost": embedding_cost_report(settings),
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False), media_type="application/json"
    )
