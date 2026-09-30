"""Celery dispatch for the RAG indexing pipeline.

The API never blocks on indexing. When ``SOURCE_PROCESSING_MODE=async`` a task is published
on the ``rag`` queue and the Celery worker calls back the internal API endpoint, which owns
the database. When the mode is ``sync`` the API performs the indexing inline, which is the
mode used by the test suite.
"""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from celery import Celery

from app.core.config import Settings

RAG_QUEUE = "rag"


@lru_cache(maxsize=8)
def _celery_client(broker_url: str, result_backend: str) -> Celery:
    client = Celery(
        "academic_memo_rag",
        broker=broker_url,
        backend=result_backend,
    )
    client.conf.update(
        broker_connection_timeout=2,
        broker_connection_retry_on_startup=True,
        task_default_queue=RAG_QUEUE,
        task_routes={"rag.*": {"queue": RAG_QUEUE}},
    )
    return client


def enqueue_rag_index(*, source_id: UUID, settings: Settings, force: bool = False) -> str:
    client = _celery_client(settings.celery_broker_url, settings.celery_result_backend)
    result = client.send_task(
        "rag.index_source",
        args=[str(source_id), force],
        retry=False,
        queue=RAG_QUEUE,
    )
    return result.id


def enqueue_rag_deindex(*, source_id: UUID, settings: Settings) -> str:
    client = _celery_client(settings.celery_broker_url, settings.celery_result_backend)
    result = client.send_task(
        "rag.deindex_source",
        args=[str(source_id)],
        retry=False,
        queue=RAG_QUEUE,
    )
    return result.id
