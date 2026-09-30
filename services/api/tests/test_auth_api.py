from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.auth.dependencies import CurrentAuth, get_current_auth
from app.auth.security import dump_oauth_state
from app.auth.service import SessionPair
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models.auth import AuthSession
from app.models.user import User


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        auth_expose_reset_token=True,
        auth_rate_limit_enabled=False,
    )


@pytest.fixture(autouse=True)
def override_dependencies(test_settings: Settings):
    async def override_session():
        yield object()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield
    app.dependency_overrides.clear()


def make_user(email: str = "student@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        display_name="Étudiant",
        is_active=True,
        email_verified_at=None,
        created_at=datetime.now(UTC),
    )


def make_session(user: User) -> AuthSession:
    return AuthSession(
        id=uuid4(),
        user_id=user.id,
        token_hash="hash",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        last_seen_at=datetime.now(UTC),
        revoked_at=None,
        user_agent=None,
        ip_address=None,
        created_at=datetime.now(UTC),
    )


def test_openapi_declares_session_and_csrf_security_schemes() -> None:
    schema = app.openapi()
    schemes = schema["components"]["securitySchemes"]

    assert schemes["APIKeyCookie"]["name"] == "ama_session"
    assert schemes["APIKeyHeader"]["name"] == "X-CSRF-Token"


@pytest.mark.asyncio
async def test_protected_route_requires_session() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_projects_route_requires_session() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/projects")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mutating_auth_routes_require_csrf() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/auth/register",
            json={"email": "csrf@example.com", "password": "a-valid-password"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tampered_csrf_cookie_is_rejected() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ama_csrf", "tampered-token")
        response = await client.post(
            "/api/auth/register",
            json={"email": "csrf-tampered@example.com", "password": "a-valid-password"},
            headers={"X-CSRF-Token": "tampered-token"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_register_sets_session_and_csrf_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()

    async def fake_create_user(*args, **kwargs):
        return user

    async def fake_create_session(*args, **kwargs):
        return SessionPair(raw_token="raw-session-token", session=make_session(user))

    monkeypatch.setattr("app.auth.router.create_password_user", fake_create_user)
    monkeypatch.setattr("app.auth.router.create_session", fake_create_session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_response = await client.get("/api/auth/csrf")
        csrf = csrf_response.json()["csrf_token"]
        response = await client.post(
            "/api/auth/register",
            json={"email": user.email, "password": "a-valid-password", "display_name": "Étudiant"},
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == user.email
    set_cookie = response.headers.get("set-cookie", "")
    assert "ama_session=raw-session-token" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "ama_csrf=" in set_cookie


@pytest.mark.asyncio
async def test_login_returns_generic_error_for_wrong_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_authenticate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.auth.router.authenticate_password", fake_authenticate)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_response = await client.get("/api/auth/csrf")
        csrf = csrf_response.json()["csrf_token"]
        response = await client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "wrong-password"},
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect."


@pytest.mark.asyncio
async def test_logout_revokes_session_and_clears_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    session = make_session(user)
    revoked: list[str] = []

    async def fake_revoke(db, *, raw_token):
        revoked.append(raw_token)

    monkeypatch.setattr("app.auth.router.revoke_session", fake_revoke)
    app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(user=user, session=session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ama_session", "raw-session-token")
        csrf_response = await client.get("/api/auth/csrf")
        csrf = csrf_response.json()["csrf_token"]
        response = await client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 200
    assert revoked == ["raw-session-token"]
    set_cookie = response.headers.get("set-cookie", "")
    assert "ama_session=" in set_cookie
    assert "Max-Age=0" in set_cookie


@pytest.mark.asyncio
async def test_project_route_rejects_a_non_member(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user("other@example.com")
    session = make_session(user)

    async def fake_get_project_access(*args, **kwargs):
        return None

    monkeypatch.setattr("app.projects.access.get_project_access", fake_get_project_access)
    app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(user=user, session=session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ama_session", "raw-session-token")
        response = await client.get(f"/api/projects/{uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_google_start_requires_csrf_and_returns_pkce_url() -> None:
    google_settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
    )
    app.dependency_overrides[get_settings] = lambda: google_settings

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        csrf_response = await client.get("/api/auth/csrf")
        csrf = csrf_response.json()["csrf_token"]
        response = await client.post(
            "/api/auth/google/start",
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://accounts.google.com/")
    assert "code_challenge=" in response.json()["authorization_url"]


@pytest.mark.asyncio
async def test_google_callback_rejects_state_mismatch() -> None:
    google_settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
    )
    app.dependency_overrides[get_settings] = lambda: google_settings
    serialized_state = dump_oauth_state(
        {"state": "expected-state", "nonce": "nonce-value", "verifier": "verifier"},
        google_settings,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ama_google_oauth", serialized_state)
        response = await client.get(
            "/api/auth/google/callback?code=authorization-code&state=wrong-state",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login?error=oauth")


@pytest.mark.asyncio
async def test_google_callback_creates_a_session_after_state_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google_settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
    )
    app.dependency_overrides[get_settings] = lambda: google_settings
    user = make_user("google@example.com")
    serialized_state = dump_oauth_state(
        {
            "state": "state-value",
            "nonce": "nonce-value",
            "verifier": "verifier-value",
            "next": "/dashboard",
        },
        google_settings,
    )

    async def fake_exchange(*args, **kwargs):
        assert kwargs["code_verifier"] == "verifier-value"
        return {"id_token": "signed-id-token", "scope": "openid email profile"}

    async def fake_verify(*args, **kwargs):
        assert kwargs["nonce"] == "nonce-value"
        return {
            "sub": "google-subject",
            "email": user.email,
            "email_verified": True,
            "name": "Google User",
        }

    async def fake_google_user(*args, **kwargs):
        return user

    async def fake_session(*args, **kwargs):
        return SessionPair(raw_token="google-raw-token", session=make_session(user))

    monkeypatch.setattr("app.auth.router.exchange_google_code", fake_exchange)
    monkeypatch.setattr("app.auth.router.verify_google_id_token_async", fake_verify)
    monkeypatch.setattr("app.auth.router.get_or_create_google_user", fake_google_user)
    monkeypatch.setattr("app.auth.router.create_session", fake_session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("ama_google_oauth", serialized_state)
        response = await client.get(
            "/api/auth/google/callback?code=authorization-code&state=state-value",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/dashboard"
    assert "ama_session=google-raw-token" in response.headers.get("set-cookie", "")
