"""Configuration, cost and security tests for the RAG layer."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.rag.cost import embedding_cost_report, estimate_cost, reference_price
from app.rag.settings import rag_tuning

SECRET = "rag-test-secret-that-is-long-enough"


def settings(**overrides: object) -> Settings:
    base = {"secret_key": SECRET}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_dimension_is_read_from_configuration_not_hardcoded() -> None:
    assert rag_tuning(settings(embedding_dimension=768)).embedding_dimension == 768
    assert rag_tuning(settings(embedding_dimension=3072)).embedding_dimension == 3072


def test_invalid_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        settings(embedding_provider="unknown")


def test_openai_provider_requires_an_api_key() -> None:
    with pytest.raises(ValueError):
        settings(embedding_provider="openai", embedding_api_key="")


def test_openai_provider_rejects_the_mock_model() -> None:
    with pytest.raises(ValueError):
        settings(
            embedding_provider="openai",
            embedding_api_key="secret",
            embedding_model="mock-hash-1536",
        )


def test_production_refuses_the_mock_provider() -> None:
    with pytest.raises(ValueError):
        settings(
            app_env="production",
            secret_key="a-strong-production-secret-key-value",
            frontend_url="https://app.example.com",
            cors_origins="https://app.example.com",
            source_worker_token="worker-token",
            embedding_provider="mock",
        )


def test_chunk_parameters_must_be_coherent() -> None:
    with pytest.raises(ValueError):
        settings(chunk_max_tokens=400, chunk_overlap_tokens=400)
    with pytest.raises(ValueError):
        settings(chunk_max_tokens=400, chunk_min_tokens=500)


def test_invalid_strategy_and_fusion_are_rejected() -> None:
    with pytest.raises(ValueError):
        settings(rag_search_strategy="magic")
    with pytest.raises(ValueError):
        settings(rag_fusion_method="bayes")


def test_invalid_reranker_is_rejected_at_this_stage() -> None:
    with pytest.raises(ValueError):
        settings(reranker_provider="cross-encoder-remote")


def test_top_k_bounds_are_validated() -> None:
    with pytest.raises(ValueError):
        settings(rag_default_top_k=80, rag_max_top_k=50)


def test_dimension_must_stay_in_a_usable_range() -> None:
    with pytest.raises(ValueError):
        settings(embedding_dimension=8)
    with pytest.raises(ValueError):
        settings(embedding_dimension=99999)


def test_cost_is_unavailable_instead_of_invented() -> None:
    config = settings(embedding_model="unknown-model", embedding_price_per_million_tokens_usd=0.0)
    cost, reason = estimate_cost(1000, config)
    assert cost is None
    assert "inconnu" in reason


def test_cost_is_computed_when_a_price_is_configured() -> None:
    config = settings(embedding_price_per_million_tokens_usd=0.02)
    cost, _ = estimate_cost(1_000_000, config)
    assert cost == pytest.approx(0.02)


def test_cost_report_is_serialisable_and_never_leaks_the_key() -> None:
    config = settings(
        embedding_provider="openai",
        embedding_api_key="super-secret-key",
        embedding_model="text-embedding-3-small",
        embedding_price_per_million_tokens_usd=0.02,
    )
    report = embedding_cost_report(config, tokens_sent=500_000, documents_indexed=3)
    assert report["available"] is True
    assert report["estimated_cost_usd"] == pytest.approx(0.01)
    assert "super-secret-key" not in str(report)


def test_reference_prices_cover_the_known_models() -> None:
    assert reference_price("text-embedding-3-small") == 0.02
    assert reference_price("model-that-does-not-exist") is None


def test_api_key_is_absent_from_the_public_rag_schema() -> None:
    from app.rag.schemas import RagSearchResponse, RagStatsResponse

    fields = set(RagSearchResponse.model_fields) | set(RagStatsResponse.model_fields)
    assert "embedding_api_key" not in fields
    assert "api_key" not in fields
