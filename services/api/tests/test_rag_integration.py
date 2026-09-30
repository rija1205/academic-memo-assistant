"""Database-backed RAG tests: isolation, provenance, indexing and permissions.

These tests require PostgreSQL with pgvector. They are skipped automatically when
``TEST_DATABASE_URL`` is not set, exactly like the existing integration suite. They are never
reported as passing when they have not actually run.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base
from app.models.project import Project
from app.models.rag import RagChunk
from app.models.source import Source, SourceBlock, SourceFile, SourcePage
from app.models.user import User
from app.projects.schemas import ProjectCreateRequest
from app.projects.service import create_project as create_project_service
from app.rag.embeddings import build_embedding_provider
from app.rag.pipeline import deindex_source, index_source
from app.rag.search.retrieval import lexical_search, semantic_search
from app.rag.settings import rag_tuning

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration

if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is required for the database-backed RAG tests.",
        allow_module_level=True,
    )

EMBEDDING_DIMENSION = 1536


@pytest_asyncio.fixture
async def rag_db():
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")

    api_dir = Path(__file__).parents[1]
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = TEST_DATABASE_URL
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_dir,
        env=migration_env,
        check=True,
        capture_output=True,
    )

    async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def rag_settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="rag-integration-secret-that-is-long-enough",
        frontend_url="http://localhost:3000",
        auth_rate_limit_enabled=False,
        source_processing_mode="sync",
        source_storage_provider="local",
        source_local_storage_path=str(tmp_path / "sources"),
        source_worker_token="worker-token",
        embedding_provider="mock",
        embedding_model="mock-hash-1536",
        embedding_dimension=EMBEDDING_DIMENSION,
    )


async def make_user(session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def make_source(
    session,
    *,
    project: Project,
    uploader: User,
    passages: list[tuple[int, str]],
    filename: str = "source.txt",
) -> Source:
    """Insert a processed source with real blocks so it can be indexed."""
    source = Source(
        project_id=project.id,
        uploaded_by=uploader.id,
        original_filename=filename,
        extension=".txt",
        mime_type="text/plain",
        size_bytes=100,
        sha256=uuid4().hex * 2,
        status="processed",
        stage="done",
        title=f"Source {filename}",
        authors=["A. Nkolo"],
        publication_year=2024,
        publication_type="article",
        page_count=1,
    )
    session.add(source)
    await session.flush()
    session.add(
        SourceFile(
            source_id=source.id,
            storage_provider="local",
            storage_key=f"projects/{project.id}/sources/{source.id}/{filename}",
            original_filename=filename,
            mime_type="text/plain",
            size_bytes=100,
            sha256=source.sha256,
        )
    )
    page = SourcePage(source_id=source.id, page_number=1, text="\n\n".join(t[1] for t in passages))
    session.add(page)
    await session.flush()
    for index, (page_number, text) in enumerate(passages):
        session.add(
            SourceBlock(
                source_id=source.id,
                page_id=page.id,
                page_number=page_number,
                block_index=index,
                block_type="paragraph",
                text=text,
                position_start=index * 100,
                position_end=index * 100 + len(text),
                provenance_id=uuid4(),
            )
        )
    await session.commit()
    await session.refresh(source)
    return source


JACQUIER_PASSAGES = [
    (1, "Le grain de jacquier contient des proteines vegetales en quantité importante."),
    (1, "Les fibres alimentaires totales du jacquier representent 20 pour cent du grain."),
]
URBAINE_PASSAGES = [
    (1, "Les budgets participatifs sont un instrument de gouvernance territoriale majeure."),
]


@pytest.mark.asyncio
async def test_indexing_is_idempotent(rag_db, rag_settings) -> None:
    owner = await make_user(rag_db, "index-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Index")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)
    tuning = rag_tuning(rag_settings)

    first = await index_source(rag_db, source_id=source.id, provider=provider, tuning=tuning)
    assert first.status == "indexed"
    assert first.chunk_count > 0

    # A second run must reuse the index instead of duplicating it.
    second = await index_source(rag_db, source_id=source.id, provider=provider, tuning=tuning)
    assert second.id == first.id
    assert second.attempts == first.attempts, "un index a jour ne doit pas etre reconstruit"

    chunks = list(
        (
            await rag_db.execute(select(RagChunk).where(RagChunk.rag_document_id == first.id))
        )
        .scalars()
        .all()
    )
    assert len(chunks) == first.chunk_count


@pytest.mark.asyncio
async def test_forced_reindex_replaces_the_chunks(rag_db, rag_settings) -> None:
    owner = await make_user(rag_db, "reindex-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Reindex")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)
    tuning = rag_tuning(rag_settings)

    first = await index_source(rag_db, source_id=source.id, provider=provider, tuning=tuning)
    before = list(
        (
            await rag_db.execute(
                select(RagChunk).where(RagChunk.rag_document_id == first.id)
            )
        )
        .scalars()
        .all()
    )
    second = await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=tuning, force=True
    )
    after = list(
        (
            await rag_db.execute(
                select(RagChunk).where(RagChunk.rag_document_id == second.id)
            )
        )
        .scalars()
        .all()
    )
    assert second.attempts == first.attempts + 1
    assert len(after) == len(before), "une reindexation remplace, elle n'ajoute pas"


@pytest.mark.asyncio
async def test_changing_the_embedding_version_invalidates_the_index(rag_db, rag_settings) -> None:
    owner = await make_user(rag_db, "version-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Version")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)

    first = await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=rag_tuning(rag_settings)
    )
    new_settings = rag_settings.model_copy(update={"embedding_version": "v2"})
    from app.rag.pipeline import document_needs_reindex

    needs, reason = await document_needs_reindex(first, rag_tuning(new_settings))
    assert needs is True
    assert reason == "signature_changed"

    rebuilt = await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=rag_tuning(new_settings)
    )
    assert rebuilt.index_signature == rag_tuning(new_settings).index_signature
    assert rebuilt.index_signature != first.index_signature


@pytest.mark.asyncio
async def test_semantic_and_lexical_search_never_leak_another_project(rag_db, rag_settings) -> None:
    owner_a = await make_user(rag_db, "iso-a@example.com")
    owner_b = await make_user(rag_db, "iso-b@example.com")
    project_a = await create_project_service(
        rag_db, owner_id=owner_a.id, payload=ProjectCreateRequest(title="Projet A")
    )
    project_b = await create_project_service(
        rag_db, owner_id=owner_b.id, payload=ProjectCreateRequest(title="Projet B")
    )
    source_a = await make_source(
        rag_db, project=project_a, uploader=owner_a, passages=JACQUIER_PASSAGES, filename="a.txt"
    )
    source_b = await make_source(
        rag_db,
        project=project_b,
        uploader=owner_b,
        passages=URBAINE_PASSAGES,
        filename="b.txt",
    )
    provider = build_embedding_provider(rag_settings)
    tuning = rag_tuning(rag_settings)
    await index_source(rag_db, source_id=source_a.id, provider=provider, tuning=tuning)
    await index_source(rag_db, source_id=source_b.id, provider=provider, tuning=tuning)

    query = "gouvernance territoriale budgets participatifs"
    query_vector = provider.embed_query(query)

    semantic_a = await semantic_search(
        rag_db, project_id=project_a.id, query_embedding=query_vector, top_k=10
    )
    assert semantic_a, "le projet A doit avoir des passages (fibres/jacquier)"
    assert all(chunk.source.id == source_a.id for chunk in semantic_a)

    lexical_a = await lexical_search(
        rag_db, project_id=project_a.id, query=query, top_k=10
    )
    assert all(chunk.source.id == source_a.id for chunk in lexical_a)
    assert not any(chunk.source.id == source_b.id for chunk in lexical_a)

    semantic_b = await semantic_search(
        rag_db, project_id=project_b.id, query_embedding=query_vector, top_k=10
    )
    assert semantic_b[0].source.id == source_b.id
    assert all(chunk.source.id == source_b.id for chunk in semantic_b)


@pytest.mark.asyncio
async def test_every_result_carries_a_complete_provenance_chain(rag_db, rag_settings) -> None:
    owner = await make_user(rag_db, "prov-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Provenance")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)
    document = await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=rag_tuning(rag_settings)
    )
    results = await semantic_search(
        rag_db,
        project_id=project.id,
        query_embedding=provider.embed_query("jacquier"),
        top_k=5,
    )
    assert results
    for chunk in results:
        assert chunk.chunk_id
        assert chunk.rag_document_id == document.id
        assert chunk.project_id == project.id
        assert chunk.source.id == source.id
        assert chunk.source.file_id is not None
        assert chunk.page_number >= 1
        assert chunk.provenance_id
        assert chunk.block_start >= 0
        assert chunk.block_end >= chunk.block_start
        assert chunk.text.strip()


@pytest.mark.asyncio
async def test_filters_narrow_the_result_set(rag_db, rag_settings) -> None:
    from app.rag.search.retrieval import RagFilters

    owner = await make_user(rag_db, "filter-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Filtres")
    )
    first = await make_source(
        rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES, filename="un.txt"
    )
    second = await make_source(
        rag_db, project=project, uploader=owner, passages=URBAINE_PASSAGES, filename="deux.txt"
    )
    provider = build_embedding_provider(rag_settings)
    tuning = rag_tuning(rag_settings)
    await index_source(rag_db, source_id=first.id, provider=provider, tuning=tuning)
    await index_source(rag_db, source_id=second.id, provider=provider, tuning=tuning)

    everything = await lexical_search(
        rag_db, project_id=project.id, query="jacquier budgets", top_k=10
    )
    assert len(everything) >= 2

    narrowed = await lexical_search(
        rag_db,
        project_id=project.id,
        query="jacquier budgets",
        top_k=10,
        filters=RagFilters(source_ids=(second.id,)),
    )
    assert narrowed
    assert all(chunk.source.id == second.id for chunk in narrowed)


@pytest.mark.asyncio
async def test_deindexing_removes_the_chunks_from_search(rag_db, rag_settings) -> None:
    owner = await make_user(rag_db, "deindex-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Desindexation")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)
    await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=rag_tuning(rag_settings)
    )
    assert await lexical_search(rag_db, project_id=project.id, query="jacquier", top_k=5)

    await deindex_source(rag_db, source_id=source.id)
    assert not await lexical_search(
        rag_db, project_id=project.id, query="jacquier", top_k=5
    ), "un passage desindexe ne doit plus etre retourne"


@pytest.mark.asyncio
async def test_hybrid_search_uses_both_retrieval_paths(rag_db, rag_settings) -> None:
    from app.rag.search.retrieval import hybrid_search

    owner = await make_user(rag_db, "hybrid-owner@example.com")
    project = await create_project_service(
        rag_db, owner_id=owner.id, payload=ProjectCreateRequest(title="Hybride")
    )
    source = await make_source(rag_db, project=project, uploader=owner, passages=JACQUIER_PASSAGES)
    provider = build_embedding_provider(rag_settings)
    await index_source(
        rag_db, source_id=source.id, provider=provider, tuning=rag_tuning(rag_settings)
    )
    outcome = await hybrid_search(
        rag_db,
        project_id=project.id,
        query="fibres alimentaires jacquier",
        query_embedding=provider.embed_query("fibres alimentaires jacquier"),
        top_k=5,
        tuning=rag_tuning(rag_settings),
        strategy="hybrid",
    )
    assert outcome.results
    assert outcome.strategy == "hybrid"
    assert outcome.fusion_method == "rrf"
    assert outcome.vector_hit_count >= 0
    assert all(chunk.project_id == project.id for chunk in outcome.results)
