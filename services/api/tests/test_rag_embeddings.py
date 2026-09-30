"""Unit tests for the embedding providers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.rag.embeddings import (
    EmbeddingDimensionMismatch,
    EmbeddingError,
    EmbeddingProviderUnavailable,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
    cosine_similarity,
)


def settings(**overrides: object) -> Settings:
    base = {"secret_key": "unit-test-secret-that-is-long-enough"}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_mock_provider_returns_configured_dimension() -> None:
    provider = MockEmbeddingProvider(dimension=64)
    vectors, usage = provider.embed_documents(["premier texte", "second texte"])
    assert provider.dimension == 64
    assert all(len(vector) == 64 for vector in vectors)
    assert usage.texts == 2
    assert usage.tokens > 0


def test_mock_provider_is_deterministic() -> None:
    first = MockEmbeddingProvider(dimension=128).embed_query("jacquier nutrition")
    second = MockEmbeddingProvider(dimension=128).embed_query("jacquier nutrition")
    assert first == second


def test_mock_provider_separates_relevant_from_unrelated_text() -> None:
    provider = MockEmbeddingProvider(dimension=512)
    query = provider.embed_query("composants nutritionnels du grain de jacquier")
    relevant = provider.embed_query("le jacquier contient des fibres et des proteines")
    unrelated = provider.embed_query("la destabilisation politique en amerique latine")
    assert cosine_similarity(query, relevant) > cosine_similarity(query, unrelated)
    assert cosine_similarity(query, relevant) > 0.0


def test_empty_text_produces_zero_vector() -> None:
    provider = MockEmbeddingProvider(dimension=32)
    vectors, usage = provider.embed_documents([""])
    assert vectors == [[0.0] * 32]
    assert usage.tokens == 0


def test_batch_call_returns_one_vector_per_text() -> None:
    provider = MockEmbeddingProvider(dimension=64)
    texts = [f"passage numero {index}" for index in range(25)]
    vectors, usage = provider.embed_documents(texts)
    assert len(vectors) == len(texts)
    assert usage.texts == 25


def test_cosine_similarity_rejects_mismatched_dimensions() -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_configuration_rejects_openai_without_api_key() -> None:
    """The settings layer refuses this configuration before the provider is even built."""
    with pytest.raises(ValueError):
        settings(embedding_provider="openai", embedding_api_key="")


def test_openai_provider_defensively_requires_api_key() -> None:
    unvalidated = Settings.model_construct(
        embedding_provider="openai",
        embedding_api_key="",
        embedding_model="text-embedding-3-small",
        embedding_dimension=64,
        embedding_api_base_url="https://api.openai.com/v1",
        embedding_request_timeout_seconds=60,
        embedding_max_retries=0,
        embedding_price_per_million_tokens_usd=0.0,
    )
    with pytest.raises(EmbeddingProviderUnavailable):
        OpenAIEmbeddingProvider(unvalidated)


def test_openai_provider_parses_vectors_and_usage() -> None:
    provider = OpenAIEmbeddingProvider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
            embedding_dimension=64,
            embedding_max_retries=0,
        )
    )
    payload = {
        "data": [{"embedding": [0.1] * 64}, {"embedding": [0.2] * 64}],
        "usage": {"total_tokens": 42},
    }
    with patch("httpx.post", return_value=_FakeResponse(200, payload)):
        vectors, usage = provider.embed_documents(["a", "b"])
    assert len(vectors) == 2
    assert usage.tokens == 42


def test_openai_provider_raises_on_dimension_mismatch() -> None:
    provider = OpenAIEmbeddingProvider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
            embedding_dimension=1536,
            embedding_max_retries=0,
        )
    )
    payload = {"data": [{"embedding": [0.1, 0.2]}], "usage": {"total_tokens": 3}}
    with patch("httpx.post", return_value=_FakeResponse(200, payload)):
        with pytest.raises(EmbeddingDimensionMismatch) as error:
            provider.embed_documents(["a"])
    assert error.value.expected == 1536
    assert error.value.actual == 2


def test_openai_provider_surfaces_api_error() -> None:
    provider = OpenAIEmbeddingProvider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
            embedding_dimension=64,
            embedding_max_retries=0,
        )
    )
    with patch("httpx.post", return_value=_FakeResponse(401, {})):
        with pytest.raises(EmbeddingProviderUnavailable):
            provider.embed_documents(["a"])


def test_openai_provider_reports_network_failure() -> None:
    provider = OpenAIEmbeddingProvider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
            embedding_dimension=64,
            embedding_max_retries=1,
        )
    )
    with patch("httpx.post", side_effect=OSError("network down")):
        with pytest.raises(EmbeddingProviderUnavailable):
            provider.embed_documents(["a"])


def test_empty_batch_is_not_sent_to_the_provider() -> None:
    provider = OpenAIEmbeddingProvider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
            embedding_dimension=64,
        )
    )
    vectors, usage = provider.embed_documents([])
    assert vectors == []
    assert usage.texts == 0


def test_factory_selects_provider_from_configuration() -> None:
    assert build_embedding_provider(settings()).name == "mock"
    provider = build_embedding_provider(
        settings(
            embedding_provider="openai",
            embedding_api_key="secret-key",
            embedding_model="text-embedding-3-small",
        )
    )
    assert provider.name == "openai"


def test_configuration_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        settings(embedding_provider="unknown")


def test_factory_rejects_unknown_provider_defensively() -> None:
    unvalidated = Settings.model_construct(
        embedding_provider="totally-unknown",
        embedding_dimension=64,
        embedding_model="whatever",
        embedding_batch_size=8,
        embedding_api_key="",
    )
    with pytest.raises(EmbeddingError):
        build_embedding_provider(unvalidated)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload
