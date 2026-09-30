import os

import httpx
from celery import Task
from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="system.ping")
def ping() -> dict[str, str]:
    """Basic task used to verify that the worker is registered."""
    return {"status": "ok", "service": "academic-memo-assistant-worker"}


@celery_app.task(
    bind=True,
    name="sources.process_source",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def process_source(self: Task, source_id: str, job_id: str) -> dict[str, object]:
    """Run the API-owned extraction pipeline for one stored source."""
    base_url = os.getenv("SOURCE_WORKER_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("SOURCE_WORKER_TOKEN", "")
    headers = {"X-Worker-Token": token} if token else {}
    try:
        response = httpx.post(
            f"{base_url}/api/internal/sources/{source_id}/process",
            params={"job_id": job_id},
            headers=headers,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Source processing failed for %s: %s", source_id, exc)
        if self.request.retries >= self.max_retries:
            try:
                httpx.post(
                    f"{base_url}/api/internal/sources/{source_id}/fail",
                    params={"job_id": job_id, "message": "Le traitement worker a échoué."},
                    headers=headers,
                    timeout=15.0,
                )
            except httpx.HTTPError:
                logger.exception("Unable to mark source %s as failed", source_id)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="rag.index_source",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def index_rag_source(self: Task, source_id: str, force: bool = False) -> dict[str, object]:
    """Chunk, embed and index one processed source through the internal API."""
    base_url = os.getenv("SOURCE_WORKER_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("SOURCE_WORKER_TOKEN", "")
    headers = {"X-Worker-Token": token} if token else {}
    try:
        response = httpx.post(
            f"{base_url}/api/internal/rag/sources/{source_id}/index",
            params={"force": "true" if force else "false"},
            headers=headers,
            timeout=600.0,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("RAG indexing failed for %s: %s", source_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="rag.deindex_source",
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def deindex_rag_source(self: Task, source_id: str) -> dict[str, object]:
    """Remove one source from the retrieval index through the internal API."""
    base_url = os.getenv("SOURCE_WORKER_URL", "http://localhost:8000").rstrip("/")
    token = os.getenv("SOURCE_WORKER_TOKEN", "")
    headers = {"X-Worker-Token": token} if token else {}
    try:
        response = httpx.post(
            f"{base_url}/api/internal/rag/sources/{source_id}/deindex",
            headers=headers,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("RAG deindexing failed for %s: %s", source_id, exc)
        raise self.retry(exc=exc)
