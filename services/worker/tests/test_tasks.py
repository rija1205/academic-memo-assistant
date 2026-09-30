from unittest.mock import Mock, patch

from app.worker.tasks import deindex_rag_source, index_rag_source, ping, process_source


def test_ping_task_is_registered() -> None:
    assert ping.run()["status"] == "ok"


def test_source_task_calls_the_internal_processing_endpoint() -> None:
    response = Mock()
    response.json.return_value = {"status": "processed"}
    with patch("app.worker.tasks.httpx.post", return_value=response) as post:
        result = process_source.run("source-1", "job-1")

    assert result == {"status": "processed"}
    assert post.call_args.args[0].endswith("/api/internal/sources/source-1/process")
    assert post.call_args.kwargs["params"] == {"job_id": "job-1"}


def test_source_task_retries_transport_errors() -> None:
    with patch("app.worker.tasks.httpx.post", side_effect=RuntimeError("network")):
        try:
            process_source.run("source-1", "job-1")
        except Exception as exc:
            assert "network" in str(exc) or "retry" in str(exc).lower()
        else:  # pragma: no cover
            raise AssertionError("The task should propagate a retryable failure.")


def test_rag_index_task_calls_the_internal_indexing_endpoint() -> None:
    response = Mock()
    response.json.return_value = {"status": "indexed"}
    with patch("app.worker.tasks.httpx.post", return_value=response) as post:
        result = index_rag_source.run("source-1", True)
    assert result == {"status": "indexed"}
    assert post.call_args.args[0].endswith("/api/internal/rag/sources/source-1/index")
    assert post.call_args.kwargs["params"] == {"force": "true"}


def test_rag_deindex_task_calls_the_internal_deindexing_endpoint() -> None:
    response = Mock()
    response.json.return_value = {"deleted_at": "2026-01-01"}
    with patch("app.worker.tasks.httpx.post", return_value=response) as post:
        deindex_rag_source.run("source-1")
    assert post.call_args.args[0].endswith("/api/internal/rag/sources/source-1/deindex")
