from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from celery import Celery

from app.core.config import Settings


@lru_cache(maxsize=8)
def _celery_client(broker_url: str, result_backend: str) -> Celery:
    client = Celery(
        "academic_memo_sources",
        broker=broker_url,
        backend=result_backend,
    )
    client.conf.update(
        broker_connection_timeout=2,
        broker_connection_retry_on_startup=True,
        task_default_queue="sources",
        task_routes={"sources.*": {"queue": "sources"}},
    )
    return client


def enqueue_source_processing(
    *,
    source_id: UUID,
    job_id: UUID,
    settings: Settings,
) -> str | None:
    if settings.source_processing_mode == "sync":
        return None
    client = _celery_client(settings.celery_broker_url, settings.celery_result_backend)
    result = client.send_task(
        "sources.process_source",
        args=[str(source_id), str(job_id)],
        retry=False,
        queue="sources",
    )
    return result.id
