"""Cost and usage accounting for the embedding provider.

Cost estimation must never block the application. When the provider does not publish a price,
or when no price is configured, the report simply states that the cost is unavailable instead
of raising or inventing a figure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import Settings, get_settings

#: Indicative price per million tokens in USD, used only when the deployment configures one.
#: These values are documentation aids, not billing guarantees: the operator can override them
#: with ``EMBEDDING_PRICE_PER_MILLION_TOKENS_USD``.
REFERENCE_PRICES_PER_MILLION_USD: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


@dataclass(frozen=True, slots=True)
class CostReport:
    """Cost state of the current deployment."""

    provider: str
    model: str
    tokens_sent: int = 0
    documents_indexed: int = 0
    price_per_million_tokens_usd: float | None = None
    estimated_cost_usd: float | None = None
    available: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reference_price(model: str) -> float | None:
    """Return the reference price of a known model, if any."""
    return REFERENCE_PRICES_PER_MILLION_USD.get(model)


def resolve_price(settings: Settings) -> float | None:
    """Resolve the price per million tokens, or ``None`` when unknown."""
    if settings.embedding_price_per_million_tokens_usd > 0:
        return settings.embedding_price_per_million_tokens_usd
    return reference_price(settings.embedding_model)


def estimate_cost(tokens: int, settings: Settings | None = None) -> tuple[float | None, str]:
    """Estimate the cost of ``tokens`` tokens without ever failing."""
    resolved = settings or get_settings()
    if tokens <= 0:
        return 0.0, "Aucun token envoyé."
    price = resolve_price(resolved)
    if price is None:
        return None, (
            f"Tarif inconnu pour le modèle « {resolved.embedding_model} ». "
            "Renseignez EMBEDDING_PRICE_PER_MILLION_TOKENS_USD pour obtenir une estimation."
        )
    return round((tokens / 1_000_000) * price, 8), "Estimation basée sur le tarif configuré."


def embedding_cost_report(
    settings: Settings | None = None, *, tokens_sent: int = 0, documents_indexed: int = 0
) -> dict[str, Any]:
    """Build a serialisable cost report for the API and the settings panel."""
    resolved = settings or get_settings()
    price = resolve_price(resolved)
    cost, reason = estimate_cost(tokens_sent, resolved)
    return CostReport(
        provider=resolved.embedding_provider,
        model=resolved.embedding_model,
        tokens_sent=tokens_sent,
        documents_indexed=documents_indexed,
        price_per_million_tokens_usd=price,
        estimated_cost_usd=cost,
        available=cost is not None,
        reason=reason,
    ).as_dict()
