from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.auth.dependencies import CurrentAuth, get_current_auth
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import app
from app.models.auth import AuthSession
from app.models.user import User


@pytest.fixture
def project_test_settings() -> Settings:
    return Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        auth_rate_limit_enabled=False,
    )


@pytest.fixture(autouse=True)
def override_project_dependencies(project_test_settings: Settings):
    async def override_session():
        yield object()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: project_test_settings
    yield
    app.dependency_overrides.clear()


def test_workspace_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/projects" in paths
    assert "/api/projects/{project_id}/outline" in paths
    assert "/api/projects/{project_id}/sections/{section_id}/content" in paths
    assert "/api/projects/{project_id}/sources/upload" in paths
    assert "/api/projects/{project_id}/sources/search" in paths
    assert "/api/projects/{project_id}/sources/{source_id}/preview" in paths
    assert "/api/internal/sources/{source_id}/process" in paths
    assert "/api/projects/{project_id}/sections/{section_id}/revisions" in paths
    detail_schema = paths["/api/projects/{project_id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert detail_schema["$ref"].endswith("/ProjectResponse")


@pytest.mark.asyncio
async def test_project_creation_requires_authentication() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/projects", json={"title": "Mémoire"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_project_creation_requires_csrf(project_test_settings: Settings) -> None:
    user = User(
        id=uuid4(),
        email="project-api@example.com",
        display_name="Test",
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session = AuthSession(
        id=uuid4(),
        user_id=user.id,
        token_hash="hash",
        expires_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    app.dependency_overrides[get_current_auth] = lambda: CurrentAuth(
        user=user,
        session=session,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/projects", json={"title": "Mémoire"})

    assert response.status_code == 403
