"""The HTTP middleware of stage 13.

One middleware wires the whole operational surface, in an order that matters:

1. assign a request identifier, so a log line, a metric and a security event can be tied to
   the same exchange;
2. consume the caller's budget **before** the handler runs, so an over-quota request is refused
   without ever reaching the database;
3. record the duration, the status and the route label;
4. apply the security headers;
5. persist the security events the handler collected.

The budget is enforced before the handler on purpose: a limiter that only counts afterwards
still pays for the work it was meant to prevent.
"""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.observability.metrics import REGISTRY
from app.observability.metrics import error as log_error
from app.observability.metrics import info as log_info
from app.security.guards import (
    apply_security_headers,
    current_event_log,
    enforce_request_budget,
)

#: Paths that must never be logged with their query string, because it may carry a token.
NOISY_PATHS = ("/auth/csrf", "/auth/login", "/auth/register", "/oauth")


def request_identifier() -> str:
    return uuid4().hex[:16]


def _http_exception_response(exc: HTTPException, request_id: str) -> JSONResponse:
    """Render an ``HTTPException`` raised inside the middleware.

    The shape matches what FastAPI produces for the same exception raised in a handler, so a
    client cannot tell the two apart, and the headers survive: ``Retry-After`` and the
    rate-limit counters are the whole point of a 429.
    """
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers={**(exc.headers or {}), "X-Request-Id": request_id},
    )


async def persist_security_events(request: Request, response: Response) -> None:
    """Write the events the handler collected.

    A failure to log must never fail the request: the user already got a correct answer, and
    turning a logging problem into an error would be a self-inflicted outage. The failure is
    itself logged.
    """
    events = current_event_log(request).as_rows()
    if not events:
        return
    try:
        from sqlalchemy import insert

        from app.db.session import session_factory
        from app.models.security import SecurityEvent

        async with session_factory() as db:
            for event in events:
                await db.execute(
                    insert(SecurityEvent).values(
                        user_id=event.get("actor_id") or None,
                        project_id=event.get("project_id"),
                        kind=event["kind"],
                        resource=event.get("resource"),
                        outcome=event.get("outcome") or "success",
                        detail=event.get("detail"),
                        ip_hash=event.get("ip_hash"),
                        path=request.url.path[:300],
                    )
                )
            await db.commit()
        for event in events:
            REGISTRY.observe_security_event(event["kind"])
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        log_error(
            "security_event_persistence_failed",
            request_id=getattr(request.state, "request_id", None),
            error=type(exc).__name__,
        )


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Request identifier, budget, metrics, headers and security events."""

    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or request_identifier()
        request.state.request_id = request_id
        current_event_log(request)

        started = time.perf_counter()
        status_code = 500
        try:
            await enforce_request_budget(request, settings=self.settings)
            response = await call_next(request)
            status_code = response.status_code
        except HTTPException as exc:
            # A budget refusal is raised here, inside the middleware, which means FastAPI's
            # exception handlers never see it: raising would escape as a 500 and lose both
            # the intended status and the Retry-After header a client needs to back off. The
            # response is therefore built here, as the framework would have built it.
            response = _http_exception_response(exc, request_id)
            status_code = response.status_code
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            REGISTRY.observe_request(
                route=_route_label(request), status_code=500, duration_ms=duration
            )
            log_error(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=type(exc).__name__,
                duration_ms=round(duration, 2),
            )
            apply_security_headers(_empty_response(), request, self.settings)
            raise

        duration = (time.perf_counter() - started) * 1000
        route = _route_label(request)
        REGISTRY.observe_request(route=route, status_code=status_code, duration_ms=duration)
        response.headers["X-Request-Id"] = request_id
        apply_security_headers(response, request, self.settings)

        if not any(marker in request.url.path for marker in NOISY_PATHS):
            log_info(
                "request",
                request_id=request_id,
                method=request.method,
                route=route,
                status=status_code,
                duration_ms=round(duration, 2),
            )

        await persist_security_events(request, response)
        return response


def _route_label(request: Request) -> str:
    from app.observability.metrics import route_of

    return route_of(request)


def _empty_response() -> Response:
    from starlette.responses import JSONResponse

    return JSONResponse(content={}, status_code=500)


__all__ = [
    "NOISY_PATHS",
    "ObservabilityMiddleware",
    "persist_security_events",
    "request_identifier",
]
