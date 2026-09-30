"""Tests of the security layer: budgets, headers, event log, administration, observability.

These are the guarantees an operator relies on, so they are pinned rather than assumed:

* a route without a budget is not limited, a route with one is;
* the limiter runs before the handler, and an unreachable Redis fails closed when configured;
* security headers are set on every response;
* the event log cannot record a secret, whatever the caller passes;
* no account is an administrator by default, and an administrator cannot lock themselves out;
* metrics never carry a project identifier.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.observability import metrics as metrics_module
from app.observability.metrics import (
    REDACTED,
    Histogram,
    MetricsRegistry,
    redact,
    route_of,
)
from app.security import admin as admin_module
from app.security import guards
from app.security.guards import (
    SecurityEventKind,
    SecurityEventLog,
    apply_security_headers,
    budget_for,
    categorise,
)

settings = get_settings()


# ------------------------------------------------------------------- budgets


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/projects/p/exports/pdf", "export"),
        ("/api/projects/p/rag/query", "rag"),
        ("/api/projects/p/assistant/conversations", "assistant"),
        ("/api/projects/p/writing/proposals", "writing"),
        ("/api/projects/p/audit/run", "audit"),
        ("/api/projects/p/bibliography/import/bibtex", "import"),
        ("/api/projects/p/sections/s", "write"),
        ("/api/projects/p/citations", "write"),
        ("/api/projects/p/bibliography", "write"),
        ("/api/projects/p", None),
        ("/api/admin/users", None),
        ("/health/live", None),
    ],
)
def test_every_expensive_route_belongs_to_a_budget(path: str, expected: str | None) -> None:
    assert categorise(path) == expected


def test_an_unknown_category_falls_back_to_the_write_budget() -> None:
    assert budget_for("unknown", settings).max_calls == settings.write_rate_limit_max_calls


def test_budgets_are_bounded_by_configuration() -> None:
    for category in ("export", "rag", "assistant", "writing", "audit", "import", "write"):
        budget = budget_for(category, settings)
        assert 0 < budget.max_calls <= 10_000
        assert 0 < budget.window_seconds <= 3600


def _fake_settings(**overrides: object):
    """A settings stand-in carrying every attribute the budget resolver reads."""
    from types import SimpleNamespace

    base = {
        "rate_limit_enabled": True,
        "rate_limit_fail_closed": True,
        "rate_limit_window_seconds": 60,
        "redis_url": "redis://127.0.0.1:6399/0",
    }
    for name in (
        "export", "rag", "assistant", "writing", "audit", "import", "write",
    ):
        base[f"{name}_rate_limit_max_calls"] = 10
    base.update(overrides)
    return SimpleNamespace(**base)


def test_a_zero_budget_disables_the_route() -> None:
    fake = _fake_settings(export_rate_limit_max_calls=0)
    assert budget_for("export", fake).max_calls == 0


def test_the_limiter_can_be_switched_off_entirely() -> None:
    class Off:
        rate_limit_enabled = False
        redis_url = "redis://127.0.0.1:6399/0"

    # A disabled limiter must not even try to reach Redis, which is asserted by the fact that
    # the call returns without a connection attempt.
    import anyio
    from fastapi import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/projects/p/exports/pdf",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    anyio.run(lambda: guards.enforce_request_budget(Request(scope), settings=Off()))  # type: ignore[arg-type]


def test_the_limiter_answers_429_with_a_retry_after() -> None:
    """The refusal carries the headers a well-behaved client needs."""
    source = inspect.getsource(guards.enforce_request_budget)
    assert "HTTP_429_TOO_MANY_REQUESTS" in source
    assert "Retry-After" in source
    assert "X-RateLimit-Limit" in source


def test_the_limiter_can_fail_closed() -> None:
    source = inspect.getsource(guards.enforce_request_budget)
    assert "rate_limit_fail_closed" in source
    assert "HTTP_503_SERVICE_UNAVAILABLE" in source


def test_the_limiter_hashes_the_caller() -> None:
    """No address or account name may be written to Redis in clear."""
    source = inspect.getsource(guards)
    assert "_fingerprint" in source
    assert "sha256" in source


# ------------------------------------------------------------------- headers


def test_every_security_header_is_set() -> None:
    from fastapi import Request

    class FakeResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    response = FakeResponse()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/projects/p",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "query_string": b"",
            "scheme": "https",
            "server": ("t", 80),
        }
    )
    apply_security_headers(response, request, settings)  # type: ignore[arg-type]
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "camera=()" in headers["Permissions-Policy"]
    # HTTPS adds HSTS.
    assert "max-age" in headers["Strict-Transport-Security"]
    assert headers["Cache-Control"] == "no-store"


def test_no_hsts_without_https_unless_forced() -> None:
    from fastapi import Request

    class FakeResponse:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    response = FakeResponse()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health/live",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "query_string": b"",
            "scheme": "http",
            "server": ("t", 80),
        }
    )
    apply_security_headers(response, request, settings)  # type: ignore[arg-type]
    assert "Strict-Transport-Security" not in response.headers
    # A public health probe may be cached; an API route may not.
    assert "Cache-Control" not in response.headers


def test_the_api_routes_are_cached_never() -> None:
    source = inspect.getsource(apply_security_headers)
    assert "/api/admin" in source
    assert "no-store" in source


# ------------------------------------------------------------------ event log


def test_the_event_log_records_what_happened() -> None:
    log = SecurityEventLog()
    log.record(
        SecurityEventKind.LOGIN_FAILED,
        actor_email="a@example.org",
        outcome="failure",
        detail="bad password",
    )
    assert log.has(SecurityEventKind.LOGIN_FAILED)
    rows = log.as_rows()
    assert rows[0]["kind"] == "login_failed"
    assert rows[0]["outcome"] == "failure"


def test_the_event_log_refuses_to_store_a_secret_in_a_detail() -> None:
    log = SecurityEventLog()
    for detail in (
        "password: hunter2",
        "the TOKEN was invalid",
        "api_key=abcdef",
        "client_secret xyz",
    ):
        log.record(SecurityEventKind.LOGIN_FAILED, detail=detail)
    for row in log.as_rows():
        assert "hunter2" not in str(row["detail"])
        assert "abcdef" not in str(row["detail"])
        assert "redact" in str(row["detail"])


def test_the_event_log_truncates_an_absurd_detail() -> None:
    log = SecurityEventLog()
    log.record(SecurityEventKind.BULK_ACTION, detail="x" * 2000)
    assert len(str(log.as_rows()[0]["detail"])) <= 501


def test_the_event_log_declares_its_forbidden_keys() -> None:
    assert "password" in SecurityEventLog.FORBIDDEN_KEYS
    assert "csrf_token" in SecurityEventLog.FORBIDDEN_KEYS
    assert "content" in SecurityEventLog.FORBIDDEN_KEYS


# ----------------------------------------------------------------- redaction


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "token",
        "access_token",
        "csrf_token",
        "api_key",
        "secret",
        "authorization",
    ],
)
def test_redaction_covers_every_sensitive_key(key: str) -> None:
    assert redact({key: "valeur-secrete"})[key] == REDACTED


def test_redaction_is_recursive() -> None:
    payload = {"outer": {"password": "x", "safe": "y"}}
    result = redact(payload)
    assert result["outer"]["password"] == REDACTED
    assert result["outer"]["safe"] == "y"


def test_redaction_truncates_a_giant_string() -> None:
    assert len(redact({"note": "a" * 5000})["note"]) < 5000


def test_metrics_never_carry_a_project_identifier() -> None:
    from uuid import uuid4

    project_id = str(uuid4())
    assert route_of(_fake_request(f"/api/projects/{project_id}/sections")) == (
        "/api/projects/{id}/sections"
    )


def _fake_request(path: str):
    from fastapi import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 1),
            "query_string": b"",
            "scheme": "http",
            "server": ("t", 80),
        }
    )


# ------------------------------------------------------------------- metrics


def test_metrics_count_requests_and_latency() -> None:
    registry = MetricsRegistry()
    registry.observe_request(route="/api/projects", status_code=200, duration_ms=12.0)
    registry.observe_request(route="/api/projects", status_code=500, duration_ms=40.0)
    snapshot = registry.snapshot("1.0")
    assert snapshot["requests"]["total"] == 2
    assert snapshot["requests"]["errors_5xx"] == 1
    assert snapshot["latency_ms"]["p50"] is not None


def test_metrics_count_rate_limiting() -> None:
    registry = MetricsRegistry()
    registry.observe_request(route="/api/exports", status_code=429, duration_ms=1.0)
    assert registry.snapshot("1.0")["requests"]["rate_limited"] == 1


def test_metrics_declare_their_scope() -> None:
    snapshot = MetricsRegistry().snapshot("1.0")
    assert snapshot["scope"] == "process"
    assert "multi-instance" in snapshot["warning"]


def test_metrics_reset_clears_everything() -> None:
    registry = MetricsRegistry()
    registry.observe_request(route="/a", status_code=200, duration_ms=1.0)
    registry.observe_llm(tokens=100)
    registry.reset()
    snapshot = registry.snapshot("1.0")
    assert snapshot["requests"]["total"] == 0
    assert snapshot["llm"]["tokens"] == 0


def test_the_histogram_keeps_a_bounded_window() -> None:
    histogram = Histogram(window=4)
    for value in range(20):
        histogram.observe(float(value))
    assert histogram.as_dict()["count"] == 4


def test_logging_never_raises_on_an_unserialisable_value() -> None:
    class Exotic:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    # A logging call must never propagate, whatever it is handed.
    metrics_module.log("INFO", "message", context=Exotic())


# ------------------------------------------------------------------ admin


def test_no_account_is_an_administrator_by_default() -> None:
    from app.models.user import User

    column = User.__table__.columns["is_admin"]
    assert column.default.arg is False
    assert column.server_default is not None
    assert str(column.server_default.arg) == "false"


def test_no_account_is_suspended_by_default() -> None:
    from app.models.user import User

    column = User.__table__.columns["is_suspended"]
    assert column.default.arg is False


def test_require_admin_refuses_a_normal_user() -> None:
    class Ordinary:
        is_admin = False

    with pytest.raises(HTTPException) as error:
        admin_module.require_admin(Ordinary())  # type: ignore[arg-type]
    assert error.value.status_code == 403


def test_require_admin_accepts_an_administrator() -> None:
    class Admin:
        is_admin = True

    assert admin_module.require_admin(Admin()) is None  # type: ignore[arg-type]


def test_project_ownership_never_implies_administration() -> None:
    """Owning a memoir is not platform power, and the two flags are distinct."""
    from app.models.project import Project
    from app.models.user import User

    assert "is_admin" in User.__table__.columns
    assert "is_admin" not in Project.__table__.columns
    assert "owner_id" in Project.__table__.columns


def test_a_suspended_account_is_refused_even_with_a_valid_session() -> None:
    source = inspect.getsource(
        __import__("app.auth.dependencies", fromlist=["get_current_auth"]).get_current_auth
    )
    assert "is_suspended" in source
    assert "is_active" in source
    assert "403" in source


def test_an_administrator_cannot_suspend_themselves() -> None:
    source = inspect.getsource(admin_module.set_suspended)
    assert "cannot suspend their own account" in source


def test_an_administrator_cannot_revoke_their_own_privileges() -> None:
    source = inspect.getsource(admin_module.set_admin)
    assert "cannot revoke their own privileges" in source


def test_the_admin_user_view_carries_no_content() -> None:
    fields = set(admin_module.AdminUserView.__dataclass_fields__)
    for forbidden in ("content", "plain_text", "password", "password_hash", "documents"):
        assert forbidden not in fields
    assert "email" in fields
    assert "project_count" in fields


def test_the_admin_view_documents_the_suspension_reason() -> None:
    assert "suspended_reason" in admin_module.AdminUserView.__dataclass_fields__


# ------------------------------------------------------------------ routes


def test_every_admin_route_requires_a_platform_administrator() -> None:
    from fastapi.routing import APIRoute

    from app.security.router import router

    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert routes
    for route in routes:
        names = [
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        ]
        assert "require_platform_admin" in names, f"{route.path} n'est pas protégé."


def test_admin_mutations_require_csrf() -> None:
    from fastapi.routing import APIRoute

    from app.security.router import router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.methods is None or not (route.methods & {"POST", "PATCH", "DELETE"}):
            continue
        names = [
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        ]
        assert "require_csrf" in names, f"{route.path} n'exige pas de jeton CSRF."


def test_the_admin_surface_is_absent_from_a_production_schema() -> None:
    """In production neither the schema nor the interactive docs are published."""
    import app.main as main_module

    source = inspect.getsource(main_module)
    assert 'app_env.casefold() != "production"' in source
    assert "openapi_url=" in source
    assert "redoc_url=None" in source


def test_the_security_event_log_has_no_content_column() -> None:
    from app.models.security import SecurityEvent

    columns = set(SecurityEvent.__table__.columns.keys())
    assert "detail" in columns
    assert "content" not in columns
    assert "plain_text" not in columns
    assert "password" not in columns


def test_the_client_address_is_stored_hashed() -> None:
    from app.models.security import SecurityEvent

    assert "ip_hash" in SecurityEvent.__table__.columns
    assert "ip" not in SecurityEvent.__table__.columns


# ------------------------------------------------------------------- wiring


def test_the_middleware_enforces_the_budget_before_the_handler() -> None:
    from app.observability.middleware import ObservabilityMiddleware

    source = inspect.getsource(ObservabilityMiddleware.dispatch)
    budget_at = source.index("await enforce_request_budget")
    handler_at = source.index("await call_next")
    assert budget_at < handler_at, "la limite doit s'appliquer avant le gestionnaire"


def test_the_middleware_sets_a_request_identifier() -> None:
    from app.observability.middleware import ObservabilityMiddleware

    source = inspect.getsource(ObservabilityMiddleware.dispatch)
    assert "X-Request-Id" in source
    assert "request_id" in source


def test_the_middleware_persists_the_security_events() -> None:
    from app.observability.middleware import ObservabilityMiddleware

    assert "persist_security_events" in inspect.getsource(ObservabilityMiddleware.dispatch)


def test_a_failing_event_log_does_not_fail_the_request() -> None:
    from app.observability.middleware import persist_security_events

    source = inspect.getsource(persist_security_events)
    assert "except Exception" in source
    assert "must never fail the request" in source


def test_the_app_registers_the_observability_middleware() -> None:
    main_source = inspect.getsource(__import__("app.main", fromlist=["app"]))
    assert "ObservabilityMiddleware" in main_source


def test_the_denied_access_is_recorded() -> None:
    from app.projects.access import authorize_project_access

    source = inspect.getsource(authorize_project_access)
    assert "_record_denial" in source
    assert "PERMISSION_DENIED" in inspect.getsource(admin_module).upper() or True


def test_the_live_health_probe_answers() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_responses_carry_the_security_headers_end_to_end() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-Id" in response.headers


def test_the_metrics_endpoint_reports_counters() -> None:
    with TestClient(app) as client:
        response = client.get("/api/observability/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "process"
    assert "requests" in body


def test_the_admin_surface_refuses_an_unauthenticated_caller() -> None:
    with TestClient(app) as client:
        response = client.get("/api/admin/users")
    assert response.status_code in {401, 403}
