"""Database-backed assistant tests: conversations, isolation, permissions and citations.

These tests require PostgreSQL with pgvector. They are skipped automatically when
``TEST_DATABASE_URL`` is not set. They are never reported as passing when they have not run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.models.project import Project
from app.models.user import User
from app.projects.schemas import ProjectCreateRequest
from app.projects.service import create_project as create_project_service
from app.rag.embeddings import build_embedding_provider
from app.rag.pipeline import index_source
from app.rag.settings import rag_tuning
from app.sources.validation import validate_upload

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration

if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is required for the database-backed assistant tests.",
        allow_module_level=True,
    )


@pytest_asyncio.fixture
async def assistant_db():
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    api_dir = Path(__file__).parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_dir,
        env=env,
        check=True,
        capture_output=True,
    )
    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def assistant_settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="assistant-integration-secret-long-enough",
        frontend_url="http://localhost:3000",
        auth_rate_limit_enabled=False,
        source_processing_mode="sync",
        source_storage_provider="local",
        source_local_storage_path=str(tmp_path / "sources"),
        source_worker_token="worker-token",
        embedding_provider="mock",
        embedding_model="mock-hash-1536",
        embedding_dimension=1536,
        llm_provider="mock",
        llm_model="gpt-4o-mini",
        assistant_rate_limit_enabled=False,
    )


async def seed_indexed_source(session, *, project: Project, uploader: User) -> str:
    """Insert a processed, indexed source so the assistant has real context."""
    validated = validate_upload(
        filename="jacquier.txt",
        declared_mime="text/plain",
        data=(
            b"Les fibres alimentaires totales representent 20 pour cent du grain de jacquier. "
            b"La teneur en proteines brutes atteint 15 pour cent de la matiere seche."
        ),
        max_size_bytes=1_000_000,
    )
    from app.models.source import Source

    source = Source(
        project_id=project.id,
        uploaded_by=uploader.id,
        original_filename=validated.safe_filename,
        extension=validated.extension,
        mime_type=validated.mime_type,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        status="processed",
        stage="done",
        title="Composition nutritionnelle du jacquier",
        authors=["A. Nkolo"],
        publication_year=2024,
        publication_type="article",
        page_count=1,
    )
    session.add(source)
    await session.flush()

    from app.models.source import SourceBlock, SourceFile, SourcePage

    session.add(
        SourceFile(
            source_id=source.id,
            storage_provider="local",
            storage_key=f"projects/{project.id}/sources/{source.id}/jacquier.txt",
            original_filename=validated.safe_filename,
            mime_type=validated.mime_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
        )
    )
    page = SourcePage(source_id=source.id, page_number=1, text=validated.data.decode("utf-8"))
    session.add(page)
    await session.flush()
    text = validated.data.decode("utf-8")
    for index, sentence in enumerate(text.split(". ")):
        if not sentence.strip():
            continue
        session.add(
            SourceBlock(
                source_id=source.id,
                page_id=page.id,
                page_number=1,
                block_index=index,
                block_type="paragraph",
                text=sentence.strip() + ".",
                position_start=index * 100,
                position_end=index * 100 + len(sentence),
                provenance_id=uuid4(),
            )
        )
    await session.commit()
    await session.refresh(source)

    provider = build_embedding_provider(assistant_settings())
    await index_source(
        session,
        source_id=source.id,
        provider=provider,
        tuning=rag_tuning(assistant_settings()),
    )
    return str(source.id)


async def make_user(session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_conversation_lifecycle(assistant_db, assistant_settings) -> None:
    from app.assistant.pipeline import (
        conversation_messages,
        create_conversation,
        delete_conversation,
        get_conversation,
        list_conversations,
    )

    owner = await make_user(assistant_db, "chat-owner@example.com")
    project = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Chat")
    )
    conversation = await create_conversation(
        assistant_db, project_id=project.id, user_id=owner.id, title="Nutrition"
    )
    assert conversation.message_count == 0

    found = await get_conversation(
        assistant_db,
        project_id=project.id,
        conversation_id=conversation.id,
        user_id=owner.id,
    )
    assert found.id == conversation.id

    conversations, total = await list_conversations(
        assistant_db, project_id=project.id, user_id=owner.id, limit=10, offset=0
    )
    assert total == 1

    await delete_conversation(assistant_db, conversation)
    assert await conversation_messages(assistant_db, conversation.id) == []
    remaining, _ = await list_conversations(
        assistant_db, project_id=project.id, user_id=owner.id, limit=10, offset=0
    )
    assert remaining == []


@pytest.mark.asyncio
async def test_conversation_of_another_user_is_not_found(assistant_db, assistant_settings) -> None:
    from fastapi import HTTPException

    from app.assistant.pipeline import create_conversation, get_conversation

    owner = await make_user(assistant_db, "chat-a@example.com")
    intruder = await make_user(assistant_db, "chat-b@example.com")
    project = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Privé")
    )
    conversation = await create_conversation(
        assistant_db, project_id=project.id, user_id=owner.id, title="Confidentiel"
    )

    with pytest.raises(HTTPException) as error:
        await get_conversation(
            assistant_db,
            project_id=project.id,
            conversation_id=conversation.id,
            user_id=intruder.id,
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_conversation_of_another_project_is_not_found(
    assistant_db, assistant_settings
) -> None:
    from fastapi import HTTPException

    from app.assistant.pipeline import create_conversation, get_conversation

    owner = await make_user(assistant_db, "chat-p@example.com")
    project_a = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="A")
    )
    project_b = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="B")
    )
    conversation = await create_conversation(
        assistant_db, project_id=project_a.id, user_id=owner.id, title="A"
    )
    with pytest.raises(HTTPException) as error:
        await get_conversation(
            assistant_db,
            project_id=project_b.id,
            conversation_id=conversation.id,
            user_id=owner.id,
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_grounded_answer_stores_validated_citations(assistant_db, assistant_settings) -> None:
    from app.assistant.llm import MockLlmProvider
    from app.assistant.pipeline import (
        create_conversation,
        generate_answer,
        message_citations,
        store_exchange,
    )

    owner = await make_user(assistant_db, "chat-ground@example.com")
    project = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Fondé")
    )
    await seed_indexed_source(assistant_db, project=project, uploader=owner)

    provider = MockLlmProvider()
    answer = await generate_answer(
        assistant_db,
        project_id=project.id,
        question="Quelle est la teneur en fibres du jacquier ?",
        history=[],
        history_summary=None,
        settings=assistant_settings,
        provider=provider,
    )
    assert answer.status == "completed"
    assert answer.chunks_retrieved > 0
    assert answer.citations, "une reponse fondee doit produire des citations"
    assert all(citation.project_id == project.id for citation in answer.citations)

    conversation = await create_conversation(
        assistant_db, project_id=project.id, user_id=owner.id, title="Test"
    )
    _, assistant_message = await store_exchange(
        assistant_db, conversation=conversation, question="Q ?", answer=answer
    )
    stored = await message_citations(assistant_db, [assistant_message.id])
    assert len(stored[assistant_message.id]) == len(answer.citations)


@pytest.mark.asyncio
async def test_assistant_never_answers_without_retrieved_context(
    assistant_db, assistant_settings
) -> None:
    """A project with no indexed source must produce insufficient_sources and no LLM call."""
    from app.assistant.llm import MockLlmProvider
    from app.assistant.pipeline import INSUFFICIENT_SOURCES_MESSAGE, generate_answer

    owner = await make_user(assistant_db, "chat-empty@example.com")
    project = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Vide")
    )
    provider = MockLlmProvider()
    answer = await generate_answer(
        assistant_db,
        project_id=project.id,
        question="Quels sont les composants du jacquier ?",
        history=[],
        history_summary=None,
        settings=assistant_settings,
        provider=provider,
    )
    assert answer.status == "insufficient_sources"
    assert answer.answer is None
    assert answer.user_message == INSUFFICIENT_SOURCES_MESSAGE
    assert provider.received == [], "aucun appel au modele ne doit avoir lieu"


@pytest.mark.asyncio
async def test_assistant_cannot_use_another_project_sources(
    assistant_db, assistant_settings
) -> None:
    from app.assistant.llm import MockLlmProvider
    from app.assistant.pipeline import generate_answer

    owner = await make_user(assistant_db, "chat-iso@example.com")
    project_a = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="A")
    )
    project_b = await create_project_service(
        assistant_db, owner_id=owner.id, payload=ProjectCreateRequest(title="B")
    )
    await seed_indexed_source(assistant_db, project=project_a, uploader=owner)
    provider = MockLlmProvider()

    answer_b = await generate_answer(
        assistant_db,
        project_id=project_b.id,
        question="Quelle est la teneur en fibres du jacquier ?",
        history=[],
        history_summary=None,
        settings=assistant_settings,
        provider=provider,
    )
    # Project B has no indexed source of its own, so no passage from project A can be used.
    assert answer_b.status == "insufficient_sources"
    assert "jacquier" not in " ".join(
        message.content for message in provider.received
    ).lower() or provider.received == []
