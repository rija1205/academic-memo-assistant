"""Rate limiting and token budget for the assistant.

Two independent guards protect the deployment:

* a sliding window on the number of questions per minute, per user and project;
* a daily token budget, per user, so a long session cannot exhaust the provider quota.

The counters live in the existing Redis instance when it is reachable, and fall back to an
in-process store otherwise. A rate limiter that cannot reach Redis must not take the
assistant down, so the failure is logged and the in-process guard is used instead.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RateLimitExceeded(RuntimeError):
    """Raised when a caller exceeds a configured budget."""

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0
    questions_remaining: int = 0
    daily_tokens_used: int = 0
    daily_tokens_remaining: int = 0


class InMemoryRateLimiter:
    """Process-local limiter used when Redis is unavailable or in tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._questions: dict[str, deque[datetime]] = defaultdict(deque)
        self._tokens: dict[str, int] = defaultdict(int)

    def _prune(self, bucket: deque[datetime], window: timedelta, now: datetime) -> None:
        threshold = now - window
        while bucket and bucket[0] < threshold:
            bucket.popleft()

    def check(
        self,
        *,
        key: str,
        max_per_minute: int,
        max_daily_tokens: int,
        estimated_tokens: int,
        now: datetime | None = None,
    ) -> RateLimitDecision:
        moment = now or datetime.now(UTC)
        with self._lock:
            bucket = self._questions[key]
            self._prune(bucket, timedelta(minutes=1), moment)
            used_tokens = self._tokens[key]
            daily_remaining = max_daily_tokens - used_tokens
            if len(bucket) >= max_per_minute:
                oldest = bucket[0]
                retry = int((oldest + timedelta(minutes=1) - moment).total_seconds()) + 1
                return RateLimitDecision(
                    allowed=False,
                    reason="rate_limited",
                    retry_after_seconds=max(retry, 1),
                    daily_tokens_used=used_tokens,
                    daily_tokens_remaining=daily_remaining,
                )
            if estimated_tokens > daily_remaining:
                return RateLimitDecision(
                    allowed=False,
                    reason="daily_token_budget_exhausted",
                    retry_after_seconds=0,
                    daily_tokens_used=used_tokens,
                    daily_tokens_remaining=daily_remaining,
                )
            bucket.append(moment)
            return RateLimitDecision(
                allowed=True,
                questions_remaining=max_per_minute - len(bucket),
                daily_tokens_used=used_tokens,
                daily_tokens_remaining=daily_remaining,
            )

    def record_tokens(self, *, key: str, tokens: int) -> int:
        with self._lock:
            self._tokens[key] += max(0, tokens)
            return self._tokens[key]

    def reset(self) -> None:
        with self._lock:
            self._questions.clear()
            self._tokens.clear()


class AssistantRateLimiter:
    """Facade that prefers Redis and degrades to the in-memory guard."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._memory = InMemoryRateLimiter()
        self._redis_client = None
        if self._settings.assistant_rate_limit_enabled:
            self._redis_client = self._connect()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(self._settings.redis_url, decode_responses=True)
            return client
        except Exception as exc:  # pragma: no cover - depends on the environment
            logger.warning("Rate limiter Redis indisponible, repli en memoire : %s", exc)
            return None

    @staticmethod
    def _keys(*, user_id: UUID, project_id: UUID) -> tuple[str, str]:
        return (
            f"assistant:questions:{user_id}:{project_id}",
            f"assistant:tokens:{user_id}",
        )

    async def check(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        estimated_tokens: int,
    ) -> RateLimitDecision:
        if not self._settings.assistant_rate_limit_enabled:
            return RateLimitDecision(allowed=True)
        question_key, token_key = self._keys(user_id=user_id, project_id=project_id)
        if self._redis_client is not None:
            try:
                return await self._check_redis(
                    question_key=question_key,
                    token_key=token_key,
                    estimated_tokens=estimated_tokens,
                )
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Limitation Redis indisponible, repli en memoire : %s", exc)
        return self._memory.check(
            key=f"{question_key}",
            max_per_minute=self._settings.assistant_max_questions_per_minute,
            max_daily_tokens=self._settings.assistant_max_daily_tokens,
            estimated_tokens=estimated_tokens,
        )

    async def _check_redis(
        self, *, question_key: str, token_key: str, estimated_tokens: int
    ) -> RateLimitDecision:
        client = self._redis_client
        window = int(timedelta(minutes=1).total_seconds())
        used_questions = int(await client.incr(question_key))
        if used_questions == 1:
            await client.expire(question_key, window)
        used_tokens = int(await client.get(token_key) or 0)
        daily_remaining = self._settings.assistant_max_daily_tokens - used_tokens
        if used_questions > self._settings.assistant_max_questions_per_minute:
            ttl = await client.ttl(question_key)
            return RateLimitDecision(
                allowed=False,
                reason="rate_limited",
                retry_after_seconds=max(int(ttl or window), 1),
                daily_tokens_used=used_tokens,
                daily_tokens_remaining=max(daily_remaining, 0),
            )
        if estimated_tokens > daily_remaining:
            return RateLimitDecision(
                allowed=False,
                reason="daily_token_budget_exhausted",
                daily_tokens_used=used_tokens,
                daily_tokens_remaining=max(daily_remaining, 0),
            )
        return RateLimitDecision(
            allowed=True,
            questions_remaining=self._settings.assistant_max_questions_per_minute
            - used_questions,
            daily_tokens_used=used_tokens,
            daily_tokens_remaining=max(daily_remaining, 0),
        )

    async def record_tokens(self, *, user_id: UUID, project_id: UUID, tokens: int) -> int:
        if tokens <= 0:
            return 0
        _, token_key = self._keys(user_id=user_id, project_id=project_id)
        if self._redis_client is not None:
            try:
                client = self._redis_client
                total = int(await client.incrby(token_key, tokens))
                if total == tokens:
                    await client.expire(token_key, int(timedelta(days=1).total_seconds()))
                return total
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Enregistrement de tokens Redis indisponible : %s", exc)
        question_key, _ = self._keys(user_id=user_id, project_id=project_id)
        return self._memory.record_tokens(key=question_key, tokens=tokens)

    async def usage(self, *, user_id: UUID, project_id: UUID) -> RateLimitDecision:
        question_key, token_key = self._keys(user_id=user_id, project_id=project_id)
        used_tokens = 0
        if self._redis_client is not None:
            try:
                used_tokens = int(await self._redis_client.get(token_key) or 0)
            except Exception:  # pragma: no cover - network dependent
                used_tokens = 0
        return RateLimitDecision(
            allowed=True,
            daily_tokens_used=used_tokens,
            daily_tokens_remaining=max(
                self._settings.assistant_max_daily_tokens - used_tokens, 0
            ),
        )


_limiter: AssistantRateLimiter | None = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> AssistantRateLimiter:
    """Process-wide limiter instance."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = AssistantRateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    """Testing helper: drop the cached limiter and its counters."""
    global _limiter
    with _limiter_lock:
        if _limiter is not None:
            _limiter._memory.reset()
        _limiter = None


async def check_assistant_limit(
    *,
    user_id: UUID,
    project_id: UUID,
    text: str,
    settings: Settings | None = None,
) -> RateLimitDecision:
    """Shared guard for every generation feature (chat and writing).

    Raises ``429`` with a ``Retry-After`` header so the frontend can tell a rate limit apart
    from a generation failure.
    """
    decision = await get_rate_limiter().check(
        user_id=user_id,
        project_id=project_id,
        estimated_tokens=len(text) // 3,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=decision.reason or "Limite d'utilisation atteinte.",
            headers={"Retry-After": str(decision.retry_after_seconds or 60)},
        )
    return decision


async def record_assistant_tokens(
    *, user_id: UUID, project_id: UUID, tokens: int
) -> int:
    """Add the consumed tokens to the daily budget of the user."""
    return await get_rate_limiter().record_tokens(
        user_id=user_id, project_id=project_id, tokens=tokens
    )
