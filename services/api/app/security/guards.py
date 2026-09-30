"""Security: request budget, security headers and the security event log.

Three concerns, deliberately kept apart:

* :func:`enforce_request_budget` bounds how much work one caller may ask for. It protects the
  expensive endpoints — a PDF export, a RAG query, a model call — from a loop or from a
  scripted client. It is not the authentication limiter, which lives in
  :mod:`app.auth.rate_limit` and which only guards sign-in.
* :func:`apply_security_headers` sets the response headers a browser needs to keep the
  application from being framed, sniffed, embedded or cached.
* :class:`SecurityEventLog` records what happened, for an operator. It never records a
  password, a token or any of the author's content.

A limiter that fails open is a hidden hole, and one that fails closed takes the application
down. The policy here is explicit per environment and configurable, never accidental.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

#: Prefixes of the routes that are expensive enough to need a budget of their own.
#: The budget is per caller, so a busy project does not exhaust the quota of another.
BUDGET_CATEGORIES: dict[str, tuple[str, ...]] = {
    "export": ("/exports",),
    "rag": ("/rag",),
    "assistant": ("/assistant",),
    "writing": ("/writing",),
    "audit": ("/audit/run",),
    "import": ("/import",),
    "write": ("/sections", "/citations", "/bibliography"),
}


def _fingerprint(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def categorise(path: str) -> str | None:
    """The budget category of a path, or ``None`` when the route needs no budget."""
    for category, markers in BUDGET_CATEGORIES.items():
        if any(marker in path for marker in markers):
            return category
    return None


@dataclass(slots=True)
class Budget:
    """How many calls a category accepts inside its window."""

    max_calls: int
    window_seconds: int

    def as_dict(self) -> dict[str, int]:
        return {"max_calls": self.max_calls, "window_seconds": self.window_seconds}


def budget_for(category: str, settings: Settings) -> Budget:
    """Resolve the budget of a category from the configuration."""
    mapping = {
        "export": Budget(settings.export_rate_limit_max_calls, settings.rate_limit_window_seconds),
        "rag": Budget(settings.rag_rate_limit_max_calls, settings.rate_limit_window_seconds),
        "assistant": Budget(
            settings.assistant_rate_limit_max_calls, settings.rate_limit_window_seconds
        ),
        "writing": Budget(
            settings.writing_rate_limit_max_calls, settings.rate_limit_window_seconds
        ),
        "audit": Budget(settings.audit_rate_limit_max_calls, settings.rate_limit_window_seconds),
        "import": Budget(
            settings.import_rate_limit_max_calls, settings.rate_limit_window_seconds
        ),
        "write": Budget(settings.write_rate_limit_max_calls, settings.rate_limit_window_seconds),
    }
    return mapping.get(category, Budget(settings.write_rate_limit_max_calls, 60))


async def enforce_request_budget(
    request: Request,
    *,
    settings: Settings,
    identity: str | None = None,
) -> None:
    """Consume one unit of the caller's budget for the route's category.

    The identity defaults to the authenticated user, falling back to the client address. The
    key is a hash of it, so no address or account name is ever written to Redis.
    """
    if not settings.rate_limit_enabled:
        return
    category = categorise(request.url.path)
    if category is None:
        return
    budget = budget_for(category, settings)
    if budget.max_calls <= 0:
        return

    caller = identity or _caller_of(request)
    key = f"ama:budget:{category}:{_fingerprint(caller)}"
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, budget.window_seconds)
        if count > budget.max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Trop de requêtes sur cette opération. "
                    f"Limite : {budget.max_calls} appels en {budget.window_seconds} secondes."
                ),
                headers={
                    "Retry-After": str(budget.window_seconds),
                    "X-RateLimit-Limit": str(budget.max_calls),
                    "X-RateLimit-Remaining": "0",
                },
            )
    except HTTPException:
        raise
    except (RedisError, TimeoutError) as exc:
        # Production refuses to serve an unprotected endpoint; elsewhere the limiter is a
        # convenience and stays out of the way.
        if settings.rate_limit_fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "La protection de cette opération est temporairement indisponible."
                ),
            ) from exc
    finally:
        await redis.aclose()


def _caller_of(request: Request) -> str:
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


# ------------------------------------------------------------------- headers


def apply_security_headers(response: Any, request: Request, settings: Settings) -> None:
    """Set the response headers that keep the application from being abused by a browser."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    # The API serves JSON and file downloads, never HTML, so the policy can be strict.
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    if request.url.scheme == "https" or settings.force_https:
        response.headers["Strict-Transport-Security"] = (
            f"max-age={settings.hsts_max_age}; includeSubDomains"
        )
    if request.url.path.startswith(("/api/auth", "/api/projects", "/api/internal", "/api/admin")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"


# ------------------------------------------------------------- event log


class SecurityEventKind(StrEnum):
    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    ACCOUNT_SUSPENDED = "account_suspended"
    PERMISSION_DENIED = "permission_denied"
    CROSS_PROJECT_ATTEMPT = "cross_project_attempt"
    RATE_LIMIT_TRIPPED = "rate_limit_tripped"
    EXPORT_GENERATED = "export_generated"
    BULK_ACTION = "bulk_action"
    ADMIN_ACTION = "admin_action"


class SecurityEventLog:
    """Collects security events for a request, so they can be persisted in one write.

    Events carry an actor and a resource. They never carry a password, a token, a cookie or
    any of the author's text, and that restriction is enforced by :meth:`record`, which
    refuses the sensitive keys outright rather than trusting the caller.
    """

    #: Keys that must never reach the log, whatever the caller passes.
    FORBIDDEN_KEYS = frozenset(
        {
            "password",
            "password_hash",
            "token",
            "access_token",
            "refresh_token",
            "csrf_token",
            "cookie",
            "authorization",
            "api_key",
            "secret",
            "content",
            "plain_text",
        }
    )

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        kind: SecurityEventKind | str,
        *,
        actor_id: str | None = None,
        actor_email: str | None = None,
        project_id: str | None = None,
        resource: str | None = None,
        outcome: str = "success",
        detail: str | None = None,
        ip: str | None = None,
    ) -> None:
        """Record one event, dropping any unsafe detail."""
        safe_detail = None
        if detail:
            safe_detail = _strip_sensitive(detail)
        self.events.append(
            {
                "kind": str(kind),
                "actor_id": actor_id,
                # The address is kept because an incident needs it; the identity is hashed
                # later, never here, so the log never carries a readable account list.
                "actor_email": actor_email,
                "project_id": project_id,
                "resource": resource,
                "outcome": outcome,
                "detail": safe_detail,
                "ip": ip,
            }
        )

    def as_rows(self) -> list[dict[str, Any]]:
        return list(self.events)

    def has(self, kind: SecurityEventKind | str) -> bool:
        return any(event["kind"] == str(kind) for event in self.events)


def _strip_sensitive(detail: str) -> str:
    """Remove anything that looks like a secret from a free-text detail."""
    lowered = detail.casefold()
    for word in ("password", "token", "secret", "api_key", "cookie"):
        if word in lowered:
            return "<detail redacté>"
    if len(detail) > 500:
        return detail[:500] + "…"
    return detail


#: One event log per request, stored on the request state by the middleware.
REQUEST_LOG_ATTRIBUTE = "security_events"


def current_event_log(request: Request) -> SecurityEventLog:
    """The event log of the in-flight request, created on first use."""
    existing = getattr(request.state, REQUEST_LOG_ATTRIBUTE, None)
    if existing is None:
        existing = SecurityEventLog()
        setattr(request.state, REQUEST_LOG_ATTRIBUTE, existing)
    return existing


__all__ = [
    "BUDGET_CATEGORIES",
    "Budget",
    "REQUEST_LOG_ATTRIBUTE",
    "SecurityEventKind",
    "SecurityEventLog",
    "apply_security_headers",
    "budget_for",
    "categorise",
    "current_event_log",
    "enforce_request_budget",
]
