"""Idempotent indexing pipeline: source blocks -> chunks -> embeddings -> pgvector.

Idempotence strategy
--------------------
Every index build carries a signature built from the embedding provider, the model, the
dimension, the embedding version and the chunking parameters
(:attr:`RagTuning.index_signature`). Re-indexing a source whose signature is unchanged and
whose status is ``indexed`` is a no-op. Any change of model, dimension or chunking settings
produces a different signature, so the application knows that previous embeddings are stale
and the source is reported as ``pending`` until it is rebuilt.

The pipeline is safe against concurrent execution: the ``RagDocument`` row is locked with
``SELECT ... FOR UPDATE`` and the old chunks of that document are replaced inside one
transaction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag import RagChunk, RagDocument, RagQuery
from app.models.source import Source, SourceBlock, SourceFile
from app.rag.chunking import AcademicChunker, SourceBlockInput
from app.rag.embeddings import EmbeddingError, EmbeddingProvider
from app.rag.search.retrieval import RagFilters, SearchOutcome, hybrid_search
from app.rag.settings import (
    RAG_STATUS_CHUNKING,
    RAG_STATUS_EMBEDDING,
    RAG_STATUS_FAILED,
    RAG_STATUS_INDEXED,
    RAG_STATUS_PENDING,
    RagTuning,
)

logger = logging.getLogger(__name__)


class IndexingError(RuntimeError):
    """Raised when a source cannot be indexed."""


async def load_source_blocks(
    db: AsyncSession, source_id: UUID
) -> list[SourceBlockInput]:
    """Load the ordered blocks of a source as chunker inputs."""
    result = await db.execute(
        select(SourceBlock)
        .where(SourceBlock.source_id == source_id)
        .order_by(SourceBlock.page_number.asc(), SourceBlock.block_index.asc())
    )
    return [
        SourceBlockInput(
            provenance_id=block.provenance_id,
            page_number=block.page_number,
            block_index=block.block_index,
            block_type=block.block_type,
            text=block.text,
            position_start=block.position_start,
            position_end=block.position_end,
        )
        for block in result.scalars().all()
        if block.text and block.text.strip()
    ]


async def get_rag_document(
    db: AsyncSession, source_id: UUID, *, for_update: bool = False
) -> RagDocument | None:
    statement = select(RagDocument).where(RagDocument.source_id == source_id)
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def document_needs_reindex(
    document: RagDocument | None, tuning: RagTuning
) -> tuple[bool, str]:
    """Decide whether an existing index can be reused."""
    if document is None:
        return True, "no_index"
    if document.deleted_at is not None:
        return True, "deindexed"
    if document.index_signature != tuning.index_signature:
        return True, "signature_changed"
    if document.status == RAG_STATUS_INDEXED:
        return False, "up_to_date"
    if document.status == RAG_STATUS_FAILED:
        return True, "previous_failure"
    return True, "incomplete"


async def index_source(
    db: AsyncSession,
    *,
    source_id: UUID,
    provider: EmbeddingProvider,
    tuning: RagTuning,
    force: bool = False,
) -> RagDocument:
    """Chunk, embed and store the passages of one source.

    Returns the ``RagDocument``. On failure the document is left in ``failed`` with an
    explanatory message and the exception is re-raised so the worker can retry.
    """
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.deleted_at.is_(None))
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise IndexingError("Source introuvable ou supprimée.")
    if source.status != "processed":
        raise IndexingError(
            "La source doit être traitée (statut « processed ») avant d'être indexée."
        )
    if provider.dimension != tuning.embedding_dimension:
        from app.rag.embeddings import EmbeddingDimensionMismatch

        raise EmbeddingDimensionMismatch(
            expected=tuning.embedding_dimension,
            actual=provider.dimension,
            model=provider.model,
        )

    file_result = await db.execute(select(SourceFile).where(SourceFile.source_id == source.id))
    source_file = file_result.scalar_one_or_none()

    document = await get_rag_document(db, source.id, for_update=True)
    needs, reason = await document_needs_reindex(document, tuning)
    if document is not None and not needs and not force:
        return document

    if document is None:
        document = RagDocument(
            project_id=source.project_id,
            source_id=source.id,
            source_file_id=source_file.id if source_file else None,
            index_signature=tuning.index_signature,
            embedding_provider=provider.name,
            embedding_model=provider.model,
            embedding_version=tuning.embedding_version,
            chunking_version=tuning.chunking_version,
            embedding_dimension=provider.dimension,
        )
        db.add(document)
    else:
        document.source_file_id = source_file.id if source_file else document.source_file_id
        document.index_signature = tuning.index_signature
        document.embedding_provider = provider.name
        document.embedding_model = provider.model
        document.embedding_version = tuning.embedding_version
        document.chunking_version = tuning.chunking_version
        document.embedding_dimension = provider.dimension
        document.status = RAG_STATUS_PENDING
        document.error_message = None
        document.indexed_at = None
    document.attempts += 1
    await db.commit()
    await db.refresh(document)

    try:
        # -- stage 1: chunking -------------------------------------------------
        document.status = RAG_STATUS_CHUNKING
        document.updated_at = datetime.now(UTC)
        await db.commit()

        blocks = await load_source_blocks(db, source.id)
        if not blocks:
            raise IndexingError("La source ne contient aucun bloc exploitable.")
        chunker = AcademicChunker(
            max_tokens=tuning.chunk_max_tokens,
            overlap_tokens=tuning.chunk_overlap_tokens,
            min_tokens=tuning.chunk_min_tokens,
        )
        chunks = chunker.chunk(blocks)

        # -- stage 2: embedding (batched) -------------------------------------
        document.status = RAG_STATUS_EMBEDDING
        document.chunk_count = len(chunks)
        document.updated_at = datetime.now(UTC)
        await db.commit()

        vectors, total_tokens, total_cost = await _embed_chunks(
            provider, [chunk.text for chunk in chunks], batch_size=tuning.embedding_batch_size
        )

        # -- stage 3: persist chunks + vectors --------------------------------
        await db.execute(delete(RagChunk).where(RagChunk.rag_document_id == document.id))
        for position, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(
                RagChunk(
                    rag_document_id=document.id,
                    project_id=source.project_id,
                    source_id=source.id,
                    source_file_id=source_file.id if source_file else None,
                    provenance_id=chunk.provenance_id,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    block_start=chunk.block_start,
                    block_end=chunk.block_end,
                    chunk_index=position,
                    token_count=chunk.token_count,
                    embedding=vector,
                    metadata_json={
                        **chunk.metadata,
                        "heading_path": list(chunk.heading_path),
                        "block_types": list(chunk.block_types),
                        "sentence_split": chunk.sentence_split,
                        "index_signature": tuning.index_signature,
                    },
                )
            )
        document.status = RAG_STATUS_INDEXED
        document.chunk_count = len(chunks)
        document.token_count = total_tokens
        document.estimated_cost_usd = round(total_cost, 8)
        document.page_count = source.page_count
        document.error_message = None
        document.indexed_at = datetime.now(UTC)
        document.updated_at = document.indexed_at
        await db.commit()
        await db.refresh(document)
        return document
    except (IndexingError, EmbeddingError, SQLAlchemyError) as exc:
        await db.rollback()
        failed = await get_rag_document(db, source_id, for_update=True)
        if failed is not None:
            failed.status = RAG_STATUS_FAILED
            failed.error_message = str(exc)[:2000]
            failed.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(failed)
        logger.warning("Indexation RAG échouée pour la source %s : %s", source_id, exc)
        raise


async def _embed_chunks(
    provider: EmbeddingProvider,
    texts: list[str],
    *,
    batch_size: int,
) -> tuple[list[list[float]], int, float]:
    """Embed chunks in batches. Never one request per chunk when batching is possible."""
    vectors: list[list[float]] = []
    total_tokens = 0
    total_cost = 0.0
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        batch_vectors, usage = provider.embed_documents(batch)
        if len(batch_vectors) != len(batch):
            raise EmbeddingError(
                "Le fournisseur d'embeddings a renvoyé un nombre de vecteurs inattendu."
            )
        vectors.extend(batch_vectors)
        total_tokens += usage.tokens
        total_cost += usage.estimated_cost_usd
    return vectors, total_tokens, total_cost


async def deindex_source(db: AsyncSession, *, source_id: UUID) -> RagDocument | None:
    """Remove a source from the retrieval index without deleting the source itself.

    The chunks are deleted immediately so they can never be returned by a search, while the
    ``RagDocument`` row is kept as a tombstone (soft delete) to preserve the deletion policy
    already in place for sources.
    """
    document = await get_rag_document(db, source_id, for_update=True)
    if document is None:
        return None
    await db.execute(delete(RagChunk).where(RagChunk.rag_document_id == document.id))
    document.deleted_at = datetime.now(UTC)
    document.status = RAG_STATUS_PENDING
    document.chunk_count = 0
    document.updated_at = document.deleted_at
    await db.commit()
    await db.refresh(document)
    return document


async def ensure_rag_document(
    db: AsyncSession, *, source: Source, provider: EmbeddingProvider, tuning: RagTuning
) -> RagDocument:
    """Create or refresh the index record for a source without chunking it."""
    document = await get_rag_document(db, source.id, for_update=True)
    if document is None:
        document = RagDocument(
            project_id=source.project_id,
            source_id=source.id,
            index_signature=tuning.index_signature,
            embedding_provider=provider.name,
            embedding_model=provider.model,
            embedding_version=tuning.embedding_version,
            chunking_version=tuning.chunking_version,
            embedding_dimension=provider.dimension,
        )
        db.add(document)
    else:
        document.deleted_at = None
        document.index_signature = tuning.index_signature
        document.embedding_provider = provider.name
        document.embedding_model = provider.model
        document.embedding_version = tuning.embedding_version
        document.chunking_version = tuning.chunking_version
        document.embedding_dimension = provider.dimension
        if document.status == RAG_STATUS_INDEXED:
            document.status = RAG_STATUS_PENDING
    await db.commit()
    await db.refresh(document)
    return document


# ------------------------------------------------------------------- project helpers


async def list_rag_documents(
    db: AsyncSession, *, project_id: UUID, include_deleted: bool = False
) -> list[RagDocument]:
    statement = select(RagDocument).where(RagDocument.project_id == project_id)
    if not include_deleted:
        statement = statement.where(RagDocument.deleted_at.is_(None))
    result = await db.execute(statement.order_by(RagDocument.created_at.desc()))
    return list(result.scalars().all())


async def rag_project_stats(db: AsyncSession, *, project_id: UUID) -> dict[str, object]:
    """Aggregate index statistics used by the UI and by the cost panel."""
    documents = await db.execute(
        select(
            func.count(RagDocument.id),
            func.count(RagDocument.id).filter(RagDocument.status == RAG_STATUS_INDEXED),
            func.coalesce(func.sum(RagDocument.chunk_count), 0),
            func.coalesce(func.sum(RagDocument.token_count), 0),
            func.coalesce(func.sum(RagDocument.estimated_cost_usd), 0.0),
        ).where(
            RagDocument.project_id == project_id,
            RagDocument.deleted_at.is_(None),
        )
    )
    total, indexed, chunks, tokens, cost = documents.one()
    pending = await db.execute(
        select(func.count(Source.id)).where(
            Source.project_id == project_id,
            Source.deleted_at.is_(None),
            Source.status == "processed",
            ~Source.id.in_(select(RagDocument.source_id).where(RagDocument.deleted_at.is_(None))),
        )
    )
    return {
        "documents_total": int(total or 0),
        "documents_indexed": int(indexed or 0),
        "documents_pending": int(pending.scalar_one() or 0),
        "chunks_total": int(chunks or 0),
        "tokens_total": int(tokens or 0),
        "estimated_cost_usd": round(float(cost or 0.0), 6),
    }


async def record_query(
    db: AsyncSession,
    *,
    project_id: UUID,
    query: str,
    outcome: SearchOutcome,
    top_k: int,
    filters: RagFilters,
) -> RagQuery:
    """Store the technical search history. No generated answer is ever stored."""
    entry = RagQuery(
        project_id=project_id,
        query_text=query[:2000],
        strategy=outcome.strategy,
        fusion_method=outcome.fusion_method,
        top_k=top_k,
        result_count=outcome.result_count,
        semantic_hits=outcome.vector_hit_count,
        lexical_hits=outcome.lexical_hit_count,
        duration_ms=outcome.duration_ms,
        filters=filters.as_dict(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_queries(
    db: AsyncSession, *, project_id: UUID, limit: int = 50
) -> list[RagQuery]:
    result = await db.execute(
        select(RagQuery)
        .where(RagQuery.project_id == project_id)
        .order_by(RagQuery.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


__all__ = [
    "IndexingError",
    "deindex_source",
    "document_needs_reindex",
    "ensure_rag_document",
    "get_rag_document",
    "hybrid_search",
    "index_source",
    "list_queries",
    "list_rag_documents",
    "load_source_blocks",
    "rag_project_stats",
    "record_query",
]
