"""Cost accounting for the assistant.

The provider's reported price is used when it exists. When it does not, the cost is reported
as an explicit estimate or as unavailable; the application never invents a billing figure and
never blocks on cost information.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.assistant.llm import LlmCompletion
from app.core.config import Settings, get_settings

#: Indicative prices per million tokens in USD. The operator can override them through
#: LLM_PRICE_INPUT_PER_MILLION_TOKENS_USD and LLM_PRICE_OUTPUT_PER_MILLION_TOKENS_USD.
REFERENCE_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4-turbo": (10.00, 30.00),
}


@dataclass(frozen=True, slots=True)
class CostReport:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None
    is_estimate: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "is_estimate": self.is_estimate,
            "reason": self.reason,
        }


def resolve_prices(
    settings: Settings, model: str | None = None
) -> tuple[float | None, float | None]:
    input_price = (
        settings.llm_price_input_per_million_tokens_usd
        if settings.llm_price_input_per_million_tokens_usd > 0
        else None
    )
    output_price = (
        settings.llm_price_output_per_million_tokens_usd
        if settings.llm_price_output_per_million_tokens_usd > 0
        else None
    )
    if input_price is None or output_price is None:
        reference = REFERENCE_PRICES.get(model or settings.llm_model)
        if reference is not None:
            input_price = input_price if input_price is not None else reference[0]
            output_price = output_price if output_price is not None else reference[1]
    return input_price, output_price


def estimate_completion_cost(
    completion: LlmCompletion, settings: Settings | None = None
) -> CostReport:
    """Estimate the cost of one completion, or state that the price is unknown."""
    resolved = settings or get_settings()
    input_tokens = completion.usage.input_tokens
    output_tokens = completion.usage.output_tokens
    total = completion.usage.total_tokens
    input_price, output_price = resolve_prices(resolved, completion.model)
    if input_price is None or output_price is None:
        return CostReport(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            cost_usd=None,
            is_estimate=True,
            reason=(
                f"Tarif inconnu pour le modele « {completion.model} ». "
                "Renseignez LLM_PRICE_INPUT_PER_MILLION_TOKENS_USD et "
                "LLM_PRICE_OUTPUT_PER_MILLION_TOKENS_USD pour une estimation."
            ),
        )
    cost = (input_tokens / 1_000_000) * input_price + (
        output_tokens / 1_000_000
    ) * output_price
    return CostReport(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        cost_usd=round(cost, 8),
        is_estimate=True,
        reason="Estimation basee sur le tarif de reference du modele.",
    )


def prompt_token_estimate(texts: list[str], settings: Settings | None = None) -> int:
    from app.assistant.llm import estimate_tokens

    return sum(estimate_tokens(text) for text in texts)
