"""Database models for the academic RAG index.

Design decisions:

* `RagDocument` is the logical link between an imported source and its index. It carries the
  index signature (embedding model, embedding version, chunking version, dimension) so a model
  change is detectable and a rebuild can be requested explicitly.
* `RagChunk` stores the passage text, the full provenance chain and the vector. The vector
  column dimension is read from the configuration, never hard-coded.
* `RagQuery` keeps a technical search history. It stores only the query string and metrics,
  never any generated answer, because no language-model generation exists at this stage.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.rag.settings import (
    RAG_STATUS_FAILED,
    RAG_STATUS_INDEXED,
    RAG_STATUS_PENDING,
    RAG_STATUSES,
    rag_tuning,
)

# The vector dimension has a single definition: app.core.config.Settings.embedding_dimension.
EMBEDDING_DIMENSION: int = rag_tuning().embedding_dimension


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_rag_documents_source"),
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{value}'" for value in RAG_STATUSES)),
            name="ck_rag_documents_status",
        ),
        Index("ix_rag_documents_project_status", "project_id", "status"),
        Index("ix_rag_documents_signature", "index_signature"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_files.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=RAG_STATUS_PENDING,
        server_default=RAG_STATUS_PENDING,
        nullable=False,
    )
    index_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    token_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    estimated_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint(
            "rag_document_id", "chunk_index", name="uq_rag_chunks_document_index"
        ),
        Index("ix_rag_chunks_project_page", "project_id", "page_number"),
        Index("ix_rag_chunks_provenance", "provenance_id"),
        Index("ix_rag_chunks_source", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    rag_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rag_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Identifier of the first source block covered by the chunk.
    provenance_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True, nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    block_start: Mapped[int] = mapped_column(Integer, nullable=False)
    block_end: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )
    #: Chunk-level context: heading path, block types, character offsets.
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RagQuery(Base):
    __tablename__ = "rag_queries"
    __table_args__ = (
        CheckConstraint(
            "strategy IN ('semantic', 'lexical', 'hybrid')",
            name="ck_rag_queries_strategy",
        ),
        Index("ix_rag_queries_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)
    fusion_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_hits: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    lexical_hits: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    filters: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


__all__ = [
    "EMBEDDING_DIMENSION",
    "RAG_STATUS_FAILED",
    "RAG_STATUS_INDEXED",
    "RagChunk",
    "RagDocument",
    "RagQuery",
]
