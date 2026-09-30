"""Embedding providers for the academic RAG index.

Two providers are available:

* :class:`MockEmbeddingProvider` - deterministic, offline, no network. It builds a real
  bag-of-words vector so that semantic similarity is meaningful in tests: passages sharing
  vocabulary obtain a high cosine score, unrelated passages obtain a low one. This makes
  Recall@K and MRR measurable without any network access.
* :class:`OpenAIEmbeddingProvider` - calls the OpenAI embeddings HTTP API in batches.

The API key is read from the server-side settings only. It is never returned by any schema
and never sent to the browser.

The configured dimension is authoritative. If a provider returns a vector of a different
size, an explicit :class:`EmbeddingDimensionMismatch` error is raised instead of letting
PostgreSQL reject the insert later.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import Settings, get_settings

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingError(RuntimeError):
    """Raised when the embedding provider cannot produce usable vectors."""


class EmbeddingDimensionMismatch(EmbeddingError):
    """Raised when the provider returns a vector whose size differs from the config."""

    def __init__(self, *, expected: int, actual: int, model: str) -> None:
        super().__init__(
            f"Le modèle d'embedding '{model}' a renvoyé {actual} dimensions, "
            f"alors que EMBEDDING_DIMENSION vaut {expected}. "
            "Alignez EMBEDDING_DIMENSION ou changez de modèle, puis réindexez."
        )
        self.expected = expected
        self.actual = actual
        self.model = model


class EmbeddingProviderUnavailable(EmbeddingError):
    """Raised when the provider cannot be reached (network, credentials, quota)."""


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    """Accounting for one batch of embeddings, used for cost estimation."""

    texts: int
    tokens: int
    estimated_cost_usd: float


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Provider-neutral contract used by the indexing pipeline."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> tuple[list[list[float]], EmbeddingUsage]: ...

    def embed_query(self, text: str) -> list[float]: ...


def tokenize_for_embedding(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization used by the deterministic provider."""
    return _TOKEN.findall(text.casefold())


class MockEmbeddingProvider:
    """Deterministic hashed bag-of-words provider (tests and offline development)."""

    def __init__(
        self,
        *,
        dimension: int,
        model: str = "mock-hash",
        price_per_million_tokens_usd: float = 0.0,
    ) -> None:
        if dimension < 8:
            raise ValueError("dimension must be at least 8")
        self._dimension = dimension
        self._model = model
        self._price = price_per_million_tokens_usd

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vectorize(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = tokenize_for_embedding(text)
        if not tokens:
            return vector
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Two independent slots: the first is the bucket, the second a sign, so
            # unrelated tokens partially cancel instead of always reinforcing.
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    def embed_documents(
        self, texts: Sequence[str]
    ) -> tuple[list[list[float]], EmbeddingUsage]:
        vectors = [self._vectorize(text) for text in texts]
        tokens = sum(len(tokenize_for_embedding(text)) for text in texts)
        return vectors, self._usage(len(texts), tokens)

    def embed_query(self, text: str) -> list[float]:
        return self._vectorize(text)

    def _usage(self, texts: int, tokens: int) -> EmbeddingUsage:
        cost = (tokens / 1_000_000) * self._price
        return EmbeddingUsage(texts=texts, tokens=tokens, estimated_cost_usd=cost)


class OpenAIEmbeddingProvider:
    """OpenAI-compatible embeddings provider (also works with compatible gateways)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.embedding_api_key:
            raise EmbeddingProviderUnavailable(
                "EMBEDDING_API_KEY est requis lorsque EMBEDDING_PROVIDER=openai."
            )
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._dimension = settings.embedding_dimension
        self._base_url = settings.embedding_api_base_url.rstrip("/")
        self._timeout = settings.embedding_request_timeout_seconds
        self._retries = settings.embedding_max_retries
        self._price = settings.embedding_price_per_million_tokens_usd

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        import httpx

        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            status_code: int | None = None
            try:
                response = httpx.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
                status_code = response.status_code
                if status_code >= 400:
                    raise EmbeddingProviderUnavailable(
                        f"Le fournisseur d'embeddings a répondu {status_code}."
                    )
                return response.json()
            except EmbeddingError as exc:
                # Dimension mismatch and malformed payloads are not transient.
                if isinstance(exc, EmbeddingDimensionMismatch):
                    raise
                last_error = exc
                if status_code is not None and status_code in {400, 401, 403, 404}:
                    break
            except Exception as exc:  # network timeout, DNS failure, connection reset
                last_error = exc
        raise EmbeddingProviderUnavailable(
            f"Impossible de contacter le fournisseur d'embeddings : {last_error}"
        ) from last_error

    def _extract(self, payload: dict[str, object], expected: int) -> tuple[list[list[float]], int]:
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise EmbeddingError("Réponse d'embedding vide ou invalide.")
        vectors: list[list[float]] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingError("Élément d'embedding invalide.")
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("Vecteur d'embedding absent.")
            if not all(isinstance(value, (int, float)) for value in vector):
                raise EmbeddingError("Vecteur d'embedding non numérique.")
            if len(vector) != expected:
                raise EmbeddingDimensionMismatch(
                    expected=expected, actual=len(vector), model=self._model
                )
            vectors.append([float(value) for value in vector])
        usage = payload.get("usage")
        tokens = 0
        if isinstance(usage, dict):
            raw_tokens = usage.get("total_tokens") or usage.get("prompt_tokens") or 0
            if isinstance(raw_tokens, (int, float)):
                tokens = int(raw_tokens)
        return vectors, tokens

    def embed_documents(
        self, texts: Sequence[str]
    ) -> tuple[list[list[float]], EmbeddingUsage]:
        if not texts:
            return [], EmbeddingUsage(texts=0, tokens=0, estimated_cost_usd=0.0)
        payload = self._post({"model": self._model, "input": list(texts)})
        vectors, tokens = self._extract(payload, self._dimension)
        if len(vectors) != len(texts):
            raise EmbeddingError(
                "Le fournisseur a renvoyé un nombre de vecteurs inattendu."
            )
        cost = (tokens / 1_000_000) * self._price
        return vectors, EmbeddingUsage(
            texts=len(texts), tokens=tokens, estimated_cost_usd=cost
        )

    def embed_query(self, text: str) -> list[float]:
        vectors, _ = self.embed_documents([text])
        return vectors[0]


def build_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Factory selecting the provider declared in the configuration."""
    resolved = settings or get_settings()
    if resolved.embedding_provider == "mock":
        return MockEmbeddingProvider(
            dimension=resolved.embedding_dimension,
            model=resolved.embedding_model,
            price_per_million_tokens_usd=resolved.embedding_price_per_million_tokens_usd,
        )
    if resolved.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(resolved)
    raise EmbeddingError(f"Fournisseur d'embeddings inconnu : {resolved.embedding_provider}")


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity used by the deterministic provider and by the tests."""
    if len(left) != len(right):
        raise EmbeddingDimensionMismatch(
            expected=len(left), actual=len(right), model="local-cosine"
        )
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)
