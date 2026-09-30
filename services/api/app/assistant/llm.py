"""Language-model provider abstraction for the academic assistant.

The application never talks to a vendor SDK directly: it depends on :class:`LlmProvider`
only. This keeps the retrieval-augmented pipeline independent from the model vendor and
leaves room for Gemini, Anthropic or a local model later without touching the pipeline.

Security rule: the API key is read from server-side settings and is never returned by any
schema, logged, or sent to the browser.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


class LlmError(RuntimeError):
    """Base class for language-model failures."""

    #: Stable category stored in the database and returned to the frontend.
    category = "llm_error"
    #: Message safe to show to a user. Never contains provider internals.
    user_message = "Le service de génération est momentanément indisponible."


class LlmTimeout(LlmError):
    category = "timeout"
    user_message = "Le service de génération a mis trop de temps à répondre."


class LlmRateLimited(LlmError):
    category = "rate_limited"
    user_message = "Le service de génération est temporairement saturé. Réessayez plus tard."


class LlmAuthenticationError(LlmError):
    category = "authentication"
    user_message = "La configuration du service de génération est invalide."


class LlmUnavailable(LlmError):
    category = "unavailable"
    user_message = "Le service de génération est momentanément indisponible."


class LlmPayloadTooLarge(LlmError):
    category = "context_too_long"
    user_message = "Le contexte est trop volumineux pour le modèle. Affinez la question."


class LlmRefusal(LlmError):
    category = "refusal"
    user_message = "Le modèle a refusé de répondre à cette demande."


class LlmInvalidResponse(LlmError):
    category = "invalid_response"
    user_message = "La réponse du modèle n'a pas pu être exploitée."


@dataclass(frozen=True, slots=True)
class LlmMessage:
    """One message of the conversation sent to the provider."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Token accounting reported by the provider, or estimated by the caller."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """A generated answer plus its usage and vendor metadata."""

    content: str
    model: str
    provider: str
    usage: LlmUsage = field(default_factory=LlmUsage)
    finish_reason: str | None = None
    refused: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
            "finish_reason": self.finish_reason,
            "refused": self.refused,
        }


@runtime_checkable
class LlmProvider(Protocol):
    """Vendor-neutral contract used by the assistant pipeline."""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete(
        self,
        *,
        messages: Sequence[LlmMessage],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LlmCompletion: ...


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate used when the provider does not report usage."""
    if not text:
        return 0
    return sum(max(1, (len(word) + 3) // 4) for word in re.findall(r"\S+", text))


def estimate_messages_tokens(messages: Sequence[LlmMessage]) -> int:
    """Estimate the prompt size including a small per-message framing overhead."""
    return sum(estimate_tokens(message.content) + 4 for message in messages)


def is_context_too_large(messages: Sequence[LlmMessage], settings: Settings) -> bool:
    return estimate_messages_tokens(messages) > settings.assistant_max_input_tokens


class MockLlmProvider:
    """Deterministic offline provider used by the whole test suite.

    The answer is assembled from the retrieved passages so that the rest of the pipeline
    (citations, validation, storage) can be exercised end to end without network access.
    It is a *simulator*, never a real generator: it only reorders sentences that are present
    in the supplied context, which makes it harmless in production, where the configuration
    refuses a mock provider.
    """

    def __init__(
        self,
        *,
        model: str = "mock-academic-v1",
        citation_ids: Sequence[str] | None = None,
        answer: str | None = None,
    ) -> None:
        self._model = model
        self._citation_ids = list(citation_ids or [])
        self._answer = answer
        #: Every prompt received, so tests can assert on the exact context sent.
        self.received: list[list[LlmMessage]] = []

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        messages: Sequence[LlmMessage],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LlmCompletion:
        self.received.append(list(messages))
        if self._answer is not None:
            return self._completion(self._answer, messages)

        context = _extract_document_context(messages)
        question = _last_user_message(messages)
        sentences: list[str] = []
        for entry in context:
            for sentence in re.split(r"(?<=[.!?])\s+", entry):
                cleaned = sentence.strip()
                if cleaned:
                    sentences.append(cleaned)
        keywords = {
            token.casefold()
            for token in re.findall(r"[a-z0-9]+", question.casefold())
            if len(token) > 3
        }
        relevant = [
            sentence
            for sentence in sentences
            if keywords & set(re.findall(r"[a-z0-9]+", sentence.casefold()))
        ]
        selected = relevant or sentences
        citation = self._citation_ids[0] if self._citation_ids else None
        body = " ".join(selected[:6])
        if not body:
            answer = "Les sources fournies ne permettent pas de répondre à cette question."
        elif citation:
            answer = f"Selon les sources disponibles, {body} [{citation}]"
        else:
            answer = f"Selon les sources disponibles, {body}"
        return self._completion(answer, messages)

    def _completion(self, answer: str, messages: Sequence[LlmMessage]) -> LlmCompletion:
        input_tokens = estimate_messages_tokens(messages)
        output_tokens = estimate_tokens(answer)
        return LlmCompletion(
            content=answer,
            model=self._model,
            provider=self.name,
            usage=LlmUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            finish_reason="stop",
        )


_EMPTY_CONTEXT_PLACEHOLDER = "(aucun passage disponible)"


def _extract_document_context(messages: Sequence[LlmMessage]) -> list[str]:
    """Return the passage bodies found in the document context block."""
    context: list[str] = []
    inside = False
    for message in messages:
        if message.role != ROLE_USER:
            continue
        for line in message.content.splitlines():
            if line.strip() == "<document_context>":
                inside = True
                continue
            if line.strip() == "</document_context>":
                inside = False
                continue
            if inside and line.strip():
                stripped = line.strip()
                # The empty-context placeholder is not a passage and must never be quoted.
                if stripped != _EMPTY_CONTEXT_PLACEHOLDER:
                    context.append(stripped)
    return context


def _last_user_message(messages: Sequence[LlmMessage]) -> str:
    for message in reversed(messages):
        if message.role == ROLE_USER:
            return message.content
    return ""


class OpenAiLlmProvider:
    """OpenAI chat-completions provider (also works with compatible gateways)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise LlmAuthenticationError(
                "LLM_API_KEY est requis lorsque LLM_PROVIDER=openai."
            )
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._base_url = settings.llm_api_base_url.rstrip("/")
        self._timeout = settings.llm_timeout_seconds
        self._retries = settings.llm_max_retries
        self._default_temperature = settings.llm_temperature
        self._default_max_tokens = settings.llm_max_output_tokens

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        messages: Sequence[LlmMessage],
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LlmCompletion:
        import httpx

        payload = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "temperature": (
                self._default_temperature if temperature is None else temperature
            ),
            "max_completion_tokens": (
                self._default_max_tokens if max_output_tokens is None else max_output_tokens
            ),
        }
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = httpx.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = LlmTimeout(str(exc))
                if attempt < self._retries:
                    continue
                break
            except httpx.HTTPError as exc:
                last_error = LlmUnavailable(str(exc))
                if attempt < self._retries:
                    continue
                break

            if response.status_code == 429:
                last_error = LlmRateLimited("rate limited")
                if attempt < self._retries:
                    continue
                break
            if response.status_code in (401, 403):
                # Never echo the provider body: it may contain key fragments.
                logger.error(
                    "LLM provider rejected the credentials (status %s)",
                    response.status_code,
                )
                raise LlmAuthenticationError("invalid credentials")
            if response.status_code == 400 and "context" in response.text.casefold():
                raise LlmPayloadTooLarge("context too long")
            if response.status_code >= 400:
                last_error = LlmUnavailable(f"status {response.status_code}")
                if attempt < self._retries:
                    continue
                break

            try:
                body = response.json()
            except ValueError as exc:  # pragma: no cover - malformed gateway answer
                raise LlmInvalidResponse("non JSON answer") from exc
            return self._parse(body, messages)

        if isinstance(last_error, LlmError):
            raise last_error
        raise LlmUnavailable(str(last_error))

    def _parse(self, body: dict, messages: Sequence[LlmMessage]) -> LlmCompletion:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmInvalidResponse("no choice returned")
        first = choices[0]
        if not isinstance(first, dict):
            raise LlmInvalidResponse("invalid choice")
        message = first.get("message")
        if not isinstance(message, dict):
            raise LlmInvalidResponse("invalid message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LlmInvalidResponse("empty content")
        finish_reason = first.get("finish_reason")
        if finish_reason == "length":
            raise LlmPayloadTooLarge("answer truncated by the model")
        if finish_reason == "content_filter":
            raise LlmRefusal("content filtered by the provider")
        usage_payload = body.get("usage")
        input_tokens = 0
        output_tokens = 0
        if isinstance(usage_payload, dict):
            prompt_tokens = usage_payload.get("prompt_tokens")
            completion_tokens = usage_payload.get("completion_tokens")
            if isinstance(prompt_tokens, (int, float)):
                input_tokens = int(prompt_tokens)
            if isinstance(completion_tokens, (int, float)):
                output_tokens = int(completion_tokens)
        if input_tokens == 0 and output_tokens == 0:
            # Fall back to a deterministic estimate so accounting is never empty.
            input_tokens = estimate_messages_tokens(messages)
            output_tokens = estimate_tokens(content)
        return LlmCompletion(
            content=content,
            model=str(body.get("model") or self._model),
            provider=self.name,
            usage=LlmUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )


def build_llm_provider(settings: Settings | None = None) -> LlmProvider:
    """Factory selecting the provider declared in the configuration."""
    resolved = settings or get_settings()
    if resolved.llm_provider == "mock":
        return MockLlmProvider(model=f"mock-academic:{resolved.llm_model}")
    if resolved.llm_provider == "openai":
        return OpenAiLlmProvider(resolved)
    raise LlmError(f"Fournisseur LLM inconnu : {resolved.llm_provider}")


Completion = LlmCompletion
Message = LlmMessage
Provider = LlmProvider
Status = Literal["ok", "insufficient_sources", "error"]
