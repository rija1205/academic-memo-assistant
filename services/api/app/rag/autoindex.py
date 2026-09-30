"""Automatic RAG indexing hook.

When a source reaches the ``processed`` state, the RAG index must be built without any user
action. This module owns that trigger so both the synchronous path and the asynchronous
worker path behave identically.

Failure policy: an indexing failure never invalidates the source. The source stays
``processed`` and readable, the index document is marked ``failed`` with a readable message,
and the user can retry with the "Réindexer" action.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.source import Source
from app.rag.dispatch import enqueue_rag_index
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.rag.pipeline import (
    IndexingError,
    ensure_rag_document,
    index_source,
)
from app.rag.settings import RAG_STATUS_FAILED, rag_tuning

logger = logging.getLogger(__name__)


async def schedule_indexing(
    db: AsyncSession, *, source: Source, settings: Settings
) -> bool:
    """Index ``source`` when it is processed. Returns True when an index was built or queued."""
    if source.status != "processed":
        return False

    try:
        provider = build_embedding_provider(settings)
    except EmbeddingError as exc:
        logger.warning("Indexation RAG impossible, fournisseur indisponible : %s", exc)
        return False

    tuning = rag_tuning(settings)
    try:
        document = await ensure_rag_document(
            db, source=source, provider=provider, tuning=tuning
        )
    except SQLAlchemyError as exc:
        logger.warning("Impossible de créer le document RAG : %s", exc)
        return False

    if settings.source_processing_mode == "async":
        try:
            enqueue_rag_index(source_id=source.id, settings=settings)
            return True
        except Exception as exc:  # broker unavailable
            logger.warning("File d'indexation RAG indisponible : %s", exc)
            document.status = RAG_STATUS_FAILED
            document.error_message = "Service d'indexation indisponible."
            document.updated_at = datetime.now(UTC)
            await db.commit()
            return False

    try:
        await index_source(db, source_id=source.id, provider=provider, tuning=tuning)
        return True
    except (IndexingError, EmbeddingError) as exc:
        # index_source already persisted the failure state on the index document.
        logger.info("Indexation RAG inline échouée pour %s : %s", source.id, exc)
        return False
