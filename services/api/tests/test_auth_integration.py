import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.auth.security import hash_token
from app.auth.service import (
    InvalidResetTokenError,
    create_password_reset_token,
    create_password_user,
    create_session,
    reset_password,
)
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.auth import AuthSession
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.projects.access import ProjectRole, authorize_project_access
from app.projects.schemas import ProjectCreateRequest
from app.projects.service import create_project as create_project_service

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration

if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is required for database-backed authentication tests.",
        allow_module_level=True,
    )


@pytest_asyncio.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    api_dir = Path(__file__).parents[1]
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = TEST_DATABASE_URL
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_dir,
        env=migration_env,
        check=True,
    )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=api_dir,
        env=migration_env,
        check=True,
    )
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db, test_settings: Settings):
    async def override_session():
        yield test_db

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: test_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest.fixture
def source_storage_path(tmp_path: Path) -> Path:
    return tmp_path / "source-storage"


@pytest.fixture
def test_settings(source_storage_path: Path) -> Settings:
    return Settings(
        secret_key="test-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        auth_rate_limit_enabled=False,
        source_processing_mode="sync",
        source_storage_provider="local",
        source_local_storage_path=str(source_storage_path),
        source_worker_token="test-worker-token",
    )


async def create_authenticated_client(
    client: httpx.AsyncClient,
    test_db,
    *,
    email: str,
) -> User:
    user = await create_password_user(
        test_db,
        email=email,
        password="a-valid-password",
        display_name="Test User",
    )
    session_pair = await create_session(
        test_db,
        user=user,
        user_agent="pytest",
        ip_address="127.0.0.1",
        ttl_days=1,
    )
    client.cookies.set("ama_session", session_pair.raw_token)
    return user


async def get_csrf(client: httpx.AsyncClient) -> str:
    response = await client.get("/api/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


async def create_project_via_api(
    client: httpx.AsyncClient,
    *,
    title: str = "Mémoire de test",
) -> dict:
    csrf = await get_csrf(client)
    response = await client.post(
        "/api/projects",
        json={"title": title, "domain": "Sciences", "education_level": "master"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return response.json()


async def upload_source_via_api(
    client: httpx.AsyncClient,
    project_id: str,
    *,
    filename: str = "notes.txt",
    content: bytes = b"Contenu scientifique de la source.",
    mime_type: str = "text/plain",
    allow_duplicate: bool = False,
):
    csrf = await get_csrf(client)
    return await client.post(
        f"/api/projects/{project_id}/sources/upload",
        files={"file": (filename, content, mime_type)},
        data={"allow_duplicate": str(allow_duplicate).lower()},
        headers={"X-CSRF-Token": csrf},
    )


@pytest.mark.asyncio
async def test_unknown_login_returns_401_without_a_server_error(
    client: httpx.AsyncClient,
) -> None:
    csrf_response = await client.get("/api/auth/csrf")
    csrf = csrf_response.json()["csrf_token"]
    response = await client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "wrong-password"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_token_is_single_use(test_db):
    user = await create_password_user(
        test_db,
        email="reset@example.com",
        password="a-valid-password",
        display_name=None,
    )
    raw_token = await create_password_reset_token(test_db, email=user.email)
    assert raw_token

    await reset_password(
        test_db,
        raw_token=raw_token,
        new_password="a-new-valid-password",
    )
    with pytest.raises(InvalidResetTokenError):
        await reset_password(
            test_db,
            raw_token=raw_token,
            new_password="another-valid-password",
        )


@pytest.mark.asyncio
async def test_session_expiration_is_rejected(
    client: httpx.AsyncClient,
    test_db,
):
    user = await create_password_user(
        test_db,
        email="expired@example.com",
        password="a-valid-password",
        display_name=None,
    )
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token("expired-raw-token"),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    test_db.add(session)
    await test_db.commit()
    client.cookies.set("ama_session", "expired-raw-token")

    response = await client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_project_isolation_between_users(client: httpx.AsyncClient, test_db):
    owner = await create_password_user(
        test_db,
        email="owner@example.com",
        password="a-valid-password",
        display_name=None,
    )
    other = await create_password_user(
        test_db,
        email="other@example.com",
        password="a-valid-password",
        display_name=None,
    )
    project = Project(owner_id=owner.id, title="Private thesis")
    test_db.add(project)
    await test_db.commit()
    await test_db.refresh(project)

    await create_authenticated_client(client, test_db, email=other.email)
    response = await client.get(f"/api/projects/{project.id}")
    assert response.status_code == 404
    outline_response = await client.get(f"/api/projects/{project.id}/outline")
    assert outline_response.status_code == 404
    listed = await client.get("/api/projects")
    assert listed.json() == []


@pytest.mark.asyncio
async def test_project_roles_are_returned_without_leaking_other_projects(
    client: httpx.AsyncClient,
    test_db,
):
    owner = await create_password_user(
        test_db,
        email="role-owner@example.com",
        password="a-valid-password",
        display_name=None,
    )
    editor = await create_password_user(
        test_db,
        email="role-editor@example.com",
        password="a-valid-password",
        display_name=None,
    )
    reader = await create_password_user(
        test_db,
        email="role-reader@example.com",
        password="a-valid-password",
        display_name=None,
    )
    project = Project(owner_id=owner.id, title="Shared thesis")
    test_db.add(project)
    await test_db.flush()
    test_db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
            ProjectMember(project_id=project.id, user_id=reader.id, role="reader"),
        ]
    )
    await test_db.commit()
    await test_db.refresh(project)

    for user, expected_role in ((owner, "owner"), (editor, "editor"), (reader, "reader")):
        await create_authenticated_client(client, test_db, email=user.email)
        response = await client.get(f"/api/projects/{project.id}/access")
        assert response.status_code == 200
        assert response.json()["role"] == expected_role


@pytest.mark.asyncio
async def test_editor_role_is_required_for_editor_actions(test_db):
    owner = await create_password_user(
        test_db,
        email="hierarchy-owner@example.com",
        password="a-valid-password",
        display_name=None,
    )
    reader = await create_password_user(
        test_db,
        email="hierarchy-reader@example.com",
        password="a-valid-password",
        display_name=None,
    )
    project = Project(owner_id=owner.id, title="Role hierarchy")
    test_db.add(project)
    await test_db.flush()
    test_db.add(ProjectMember(project_id=project.id, user_id=reader.id, role="reader"))
    await test_db.commit()

    with pytest.raises(HTTPException) as error:
        await authorize_project_access(
            test_db,
            project_id=project.id,
            user_id=reader.id,
            required_role=ProjectRole.EDITOR,
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_project_workspace_crud_outline_and_history(client: httpx.AsyncClient, test_db):
    await create_authenticated_client(
        client,
        test_db,
        email="workspace-owner@example.com",
    )
    project_data = await create_project_via_api(client, title="Mémoire complet")
    project_id = project_data["id"]
    assert project_data["section_count"] == 13

    detail = await client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    outline = (await client.get(f"/api/projects/{project_id}/outline")).json()
    assert len(outline) == 13
    first_section = outline[0]["section_id"]

    csrf = await get_csrf(client)
    saved = await client.put(
        f"/api/projects/{project_id}/sections/{first_section}/content",
        json={
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": " premier contenu"}],
                    }
                ],
            },
            "plain_text": "contenu manipulé",
            "expected_version": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2
    assert saved.json()["plain_text"] == "premier contenu"
    conflict = await client.put(
        f"/api/projects/{project_id}/sections/{first_section}/content",
        json={
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
            "expected_version": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert conflict.status_code == 409

    updated = await client.patch(
        f"/api/projects/{project_id}",
        json={"title": "Mémoire complet modifié"},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Mémoire complet modifié"

    new_node = await client.post(
        f"/api/projects/{project_id}/outline",
        json={"parent_id": outline[0]["id"], "kind": "subsection", "title": "Sous-section"},
        headers={"X-CSRF-Token": csrf},
    )
    assert new_node.status_code == 201
    assert new_node.json()["kind"] == "subsection"

    invalid = await client.post(
        f"/api/projects/{project_id}/outline",
        json={"kind": "subsection", "title": "Racine invalide"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422

    second_save = await client.put(
        f"/api/projects/{project_id}/sections/{first_section}/content",
        json={
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "deuxième contenu"}],
                    }
                ],
            },
            "expected_version": 2,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert second_save.status_code == 200
    revisions_response = await client.get(
        f"/api/projects/{project_id}/sections/{first_section}/revisions"
    )
    revisions = revisions_response.json()
    assert len(revisions) == 3
    restore = await client.post(
        f"/api/projects/{project_id}/sections/{first_section}/revisions/{revisions[-1]['id']}/restore",
        json={},
        headers={"X-CSRF-Token": csrf},
    )
    assert restore.status_code == 200
    assert restore.json()["version"] == 4
    assert restore.json()["plain_text"] == "premier contenu"

    duplicate = await client.post(
        f"/api/projects/{project_id}/duplicate",
        json={"title": "Copie de mémoire"},
        headers={"X-CSRF-Token": csrf},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["title"] == "Copie de mémoire"
    assert (await client.get(f"/api/projects/{duplicate.json()['id']}/outline")).json()

    csrf = await get_csrf(client)
    deleted = await client.delete(
        f"/api/projects/{duplicate.json()['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 204
    assert (await client.get(f"/api/projects/{duplicate.json()['id']}")).status_code == 404

    archived = await client.post(
        f"/api/projects/{project_id}/archive",
        headers={"X-CSRF-Token": csrf},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_reader_cannot_edit_but_editor_can(client: httpx.AsyncClient, test_db):
    owner = await create_authenticated_client(
        client,
        test_db,
        email="permission-owner@example.com",
    )
    project = await create_project_service(
        test_db,
        owner_id=owner.id,
        payload=ProjectCreateRequest(title="Permission"),
    )
    editor = await create_password_user(
        test_db,
        email="permission-editor@example.com",
        password="a-valid-password",
        display_name=None,
    )
    reader = await create_password_user(
        test_db,
        email="permission-reader@example.com",
        password="a-valid-password",
        display_name=None,
    )
    test_db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
            ProjectMember(project_id=project.id, user_id=reader.id, role="reader"),
        ]
    )
    await test_db.commit()
    outline = (await client.get(f"/api/projects/{project.id}/outline")).json()
    section_id = outline[0]["section_id"]

    await create_authenticated_client(client, test_db, email=editor.email)
    csrf = await get_csrf(client)
    editor_save = await client.put(
        f"/api/projects/{project.id}/sections/{section_id}/content",
        json={
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
            "expected_version": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert editor_save.status_code == 200
    csrf = await get_csrf(client)
    editor_status = await client.patch(
        f"/api/projects/{project.id}",
        json={"status": "completed"},
        headers={"X-CSRF-Token": csrf},
    )
    assert editor_status.status_code == 403

    await create_authenticated_client(client, test_db, email=reader.email)
    csrf = await get_csrf(client)
    reader_save = await client.put(
        f"/api/projects/{project.id}/sections/{section_id}/content",
        json={
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
            "expected_version": 2,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert reader_save.status_code == 403


@pytest.mark.asyncio
async def test_source_upload_preview_search_and_duplicate_confirmation(
    client: httpx.AsyncClient,
    test_db,
):
    await create_authenticated_client(
        client,
        test_db,
        email="source-owner@example.com",
    )
    project = await create_project_via_api(client, title="Projet sources")
    project_id = project["id"]

    uploaded = await upload_source_via_api(client, project_id)
    assert uploaded.status_code == 201
    source = uploaded.json()["source"]
    assert source["status"] == "processed"
    assert source["sha256"]
    assert source["page_count"] == 1

    listed = await client.get(f"/api/projects/{project_id}/sources")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    preview = await client.get(f"/api/projects/{project_id}/sources/{source['id']}/preview")
    assert preview.status_code == 200
    assert "Contenu scientifique" in preview.json()["pages"][0]["text"]
    assert preview.json()["pages"][0]["blocks"][0]["provenance_id"]

    search = await client.get(f"/api/projects/{project_id}/sources/search?q=scientifique")
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["results"][0]["page_number"] == 1
    assert search.json()["results"][0]["provenance_id"]

    duplicate = await upload_source_via_api(client, project_id)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_file"
    allowed_duplicate = await upload_source_via_api(
        client,
        project_id,
        filename="copie.txt",
        allow_duplicate=True,
    )
    assert allowed_duplicate.status_code == 201


@pytest.mark.asyncio
async def test_source_permissions_and_project_isolation(client: httpx.AsyncClient, test_db):
    owner = await create_authenticated_client(
        client,
        test_db,
        email="source-security-owner@example.com",
    )
    project = await create_project_service(
        test_db,
        owner_id=owner.id,
        payload=ProjectCreateRequest(title="Sources privées"),
    )
    uploaded = await upload_source_via_api(client, str(project.id))
    assert uploaded.status_code == 201
    source_id = uploaded.json()["source"]["id"]

    other = await create_password_user(
        test_db,
        email="source-intruder@example.com",
        password="a-valid-password",
        display_name=None,
    )
    await create_authenticated_client(client, test_db, email=other.email)
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}")
    ).status_code == 404
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}/download")
    ).status_code == 404

    editor = await create_password_user(
        test_db,
        email="source-editor@example.com",
        password="a-valid-password",
        display_name=None,
    )
    reader = await create_password_user(
        test_db,
        email="source-reader@example.com",
        password="a-valid-password",
        display_name=None,
    )
    test_db.add_all(
        [
            ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
            ProjectMember(project_id=project.id, user_id=reader.id, role="reader"),
        ]
    )
    await test_db.commit()

    await create_authenticated_client(client, test_db, email=editor.email)
    csrf = await get_csrf(client)
    assert (
        await upload_source_via_api(client, str(project.id), filename="editor.txt")
    ).status_code == 201
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}/download")
    ).status_code == 200
    assert (await client.patch(
        f"/api/projects/{project.id}/sources/{source_id}",
        json={"title": "Titre editor", "tags": ["important"]},
        headers={"X-CSRF-Token": csrf},
    )).status_code == 200

    await create_authenticated_client(client, test_db, email=reader.email)
    csrf = await get_csrf(client)
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}")
    ).status_code == 200
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}/preview")
    ).status_code == 200
    assert (
        await upload_source_via_api(client, str(project.id), filename="reader.txt")
    ).status_code == 403
    assert (
        await client.get(f"/api/projects/{project.id}/sources/{source_id}/download")
    ).status_code == 403
    assert (await client.delete(
        f"/api/projects/{project.id}/sources/{source_id}",
        headers={"X-CSRF-Token": csrf},
    )).status_code == 403
