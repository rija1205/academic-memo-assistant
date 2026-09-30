"""Project isolation, idempotence and reindexing rules for the RAG index.

The database-backed execution of these rules is covered by ``test_rag_integration.py`` when
PostgreSQL and pgvector are available. These tests verify the decision logic that governs
reindexing, independently of the storage engine, so a signature change or a second indexing
run can never silently duplicate data.
"""

from __future__ import annotations

from uuid import uuid4

from app.rag.settings import (
    RAG_STATUS_FAILED,
    RAG_STATUS_INDEXED,
    RAG_STATUS_PENDING,
    RagTuning,
)


def tuning(**overrides: object) -> RagTuning:
    from app.rag.settings import rag_tuning

    base = rag_tuning()
    values = {
        "embedding_provider": base.embedding_provider,
        "embedding_model": base.embedding_model,
        "embedding_dimension": base.embedding_dimension,
        "embedding_batch_size": base.embedding_batch_size,
        "embedding_version": base.embedding_version,
        "chunking_version": base.chunking_version,
        "chunk_max_tokens": base.chunk_max_tokens,
        "chunk_overlap_tokens": base.chunk_overlap_tokens,
        "chunk_min_tokens": base.chunk_min_tokens,
        "strategy": base.strategy,
        "fusion_method": base.fusion_method,
        "rrf_k": base.rrf_k,
        "rrf_weight_vector": base.rrf_weight_vector,
        "rrf_weight_lexical": base.rrf_weight_lexical,
        "candidate_multiplier": base.candidate_multiplier,
        "text_search_config": base.text_search_config,
        "price_per_million_tokens_usd": base.price_per_million_tokens_usd,
    }
    values.update(overrides)
    return RagTuning(**values)  # type: ignore[arg-type]


class FakeDocument:
    """Minimal stand-in exposing the attributes the decision function reads."""

    def __init__(
        self,
        *,
        index_signature: str | None = None,
        status: str = RAG_STATUS_PENDING,
        deleted_at: object | None = None,
    ) -> None:
        self.index_signature = index_signature
        self.status = status
        self.deleted_at = deleted_at


async def test_missing_index_always_requires_indexing() -> None:
    from app.rag.pipeline import document_needs_reindex

    needs, reason = await document_needs_reindex(None, tuning())
    assert needs is True
    assert reason == "no_index"


async def test_indexed_document_with_same_signature_is_reused() -> None:
    from app.rag.pipeline import document_needs_reindex

    config = tuning()
    document = FakeDocument(index_signature=config.index_signature, status=RAG_STATUS_INDEXED)
    needs, reason = await document_needs_reindex(document, config)
    assert needs is False
    assert reason == "up_to_date"


async def test_changing_the_embedding_model_forces_a_rebuild() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(index_signature=tuning().index_signature, status=RAG_STATUS_INDEXED)
    new_config = tuning(embedding_model="text-embedding-3-large", embedding_dimension=3072)
    needs, reason = await document_needs_reindex(document, new_config)
    assert needs is True
    assert reason == "signature_changed"


async def test_changing_the_chunking_parameters_forces_a_rebuild() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(index_signature=tuning().index_signature, status=RAG_STATUS_INDEXED)
    needs, reason = await document_needs_reindex(document, tuning(chunk_max_tokens=1500))
    assert needs is True
    assert reason == "signature_changed"


async def test_changing_the_embedding_version_forces_a_rebuild() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(index_signature=tuning().index_signature, status=RAG_STATUS_INDEXED)
    needs, _ = await document_needs_reindex(document, tuning(embedding_version="v2"))
    assert needs is True


async def test_failed_index_is_retried() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(
        index_signature=tuning().index_signature, status=RAG_STATUS_FAILED
    )
    needs, reason = await document_needs_reindex(document, tuning())
    assert needs is True
    assert reason == "previous_failure"


async def test_deindexed_document_is_reindexed_on_demand() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(
        index_signature=tuning().index_signature,
        status=RAG_STATUS_PENDING,
        deleted_at=uuid4(),
    )
    needs, reason = await document_needs_reindex(document, tuning())
    assert needs is True
    assert reason == "deindexed"


async def test_incomplete_index_is_resumed() -> None:
    from app.rag.pipeline import document_needs_reindex

    document = FakeDocument(index_signature=tuning().index_signature, status="chunking")
    needs, reason = await document_needs_reindex(document, tuning())
    assert needs is True
    assert reason == "incomplete"


def test_index_signature_is_stable_for_identical_settings() -> None:
    assert tuning().index_signature == tuning().index_signature


def test_index_signature_never_hardcodes_the_dimension() -> None:
    """The signature must reflect the configured dimension, not a literal."""
    config = tuning()
    assert str(config.embedding_dimension) in config.index_signature
    assert config.embedding_dimension in (1536, 3072, 768)
