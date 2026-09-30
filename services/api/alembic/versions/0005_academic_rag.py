"""Add the academic RAG index: documents, chunks with pgvector, and query history.

Revision ID: 0005_academic_rag
Revises: 0004_source_library
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_academic_rag"
down_revision: str | None = "0004_source_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_dimension() -> int:
    """Read the vector dimension from the single application configuration.

    The dimension is never duplicated as a literal in this file: changing
    ``EMBEDDING_DIMENSION`` changes the schema, the models and the search layer at once.
    """
    from app.core.config import get_settings

    return get_settings().embedding_dimension


def upgrade() -> None:
    # pgvector is required by this migration only. It is created defensively so that a
    # database provisioned by the Docker init script is not broken, while a bare
    # PostgreSQL instance still receives the extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "rag_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("index_signature", sa.String(length=255), nullable=False),
        sa.Column("embedding_provider", sa.String(length=32), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_version", sa.String(length=64), nullable=False),
        sa.Column("chunking_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["source_files.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_rag_documents_source"),
        sa.CheckConstraint(
            "status IN ('pending', 'chunking', 'embedding', 'indexed', 'failed')",
            name="ck_rag_documents_status",
        ),
    )
    op.create_index("ix_rag_documents_project_id", "rag_documents", ["project_id"])
    op.create_index("ix_rag_documents_source_id", "rag_documents", ["source_id"])
    op.create_index("ix_rag_documents_source_file_id", "rag_documents", ["source_file_id"])
    op.create_index("ix_rag_documents_deleted_at", "rag_documents", ["deleted_at"])
    op.create_index(
        "ix_rag_documents_project_status", "rag_documents", ["project_id", "status"]
    )
    op.create_index(
        "ix_rag_documents_signature", "rag_documents", ["index_signature"]
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rag_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provenance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("block_start", sa.Integer(), nullable=False),
        sa.Column("block_end", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(_embedding_dimension()), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rag_document_id"], ["rag_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["source_files.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rag_document_id", "chunk_index", name="uq_rag_chunks_document_index"
        ),
    )
    op.create_index("ix_rag_chunks_rag_document_id", "rag_chunks", ["rag_document_id"])
    op.create_index("ix_rag_chunks_project_id", "rag_chunks", ["project_id"])
    op.create_index("ix_rag_chunks_source_id", "rag_chunks", ["source_id"])
    op.create_index("ix_rag_chunks_provenance_id", "rag_chunks", ["provenance_id"])
    op.create_index("ix_rag_chunks_project_page", "rag_chunks", ["project_id", "page_number"])
    op.create_index("ix_rag_chunks_source", "rag_chunks", ["source_id"])

    op.create_table(
        "rag_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("fusion_method", sa.String(length=16), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("semantic_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lexical_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "strategy IN ('semantic', 'lexical', 'hybrid')",
            name="ck_rag_queries_strategy",
        ),
    )
    op.create_index("ix_rag_queries_project_id", "rag_queries", ["project_id"])
    op.create_index("ix_rag_queries_created_at", "rag_queries", ["created_at"])
    op.create_index(
        "ix_rag_queries_project_created", "rag_queries", ["project_id", "created_at"]
    )

    _create_search_indexes()


def _create_search_indexes() -> None:
    """Create the retrieval indexes.

    * ``ivfflat``/``hnsw`` vector index: created in a way that works on a fresh database
      (HNSW is the default; it does not require pre-populated rows unlike IVFFlat).
    * GIN full-text index on the chunk text for lexical retrieval.
    * GIN trigram index to support partial and misspelled terms.
    * ``ivfflat`` is avoided on purpose because it builds an empty index on a new table and
      would return no rows until the table is vacuumed.
    """
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw "
        "ON rag_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_text_gin "
        "ON rag_chunks USING gin (to_tsvector('simple', text))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_text_trgm "
        "ON rag_chunks USING gin (text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_text_gin")
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw")
    op.drop_index("ix_rag_queries_project_created", table_name="rag_queries")
    op.drop_index("ix_rag_queries_created_at", table_name="rag_queries")
    op.drop_index("ix_rag_queries_project_id", table_name="rag_queries")
    op.drop_table("rag_queries")

    op.drop_index("ix_rag_chunks_source", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_project_page", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_provenance_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_source_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_project_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_rag_document_id", table_name="rag_chunks")
    op.drop_table("rag_chunks")

    op.drop_index("ix_rag_documents_signature", table_name="rag_documents")
    op.drop_index("ix_rag_documents_project_status", table_name="rag_documents")
    op.drop_index("ix_rag_documents_deleted_at", table_name="rag_documents")
    op.drop_index("ix_rag_documents_source_file_id", table_name="rag_documents")
    op.drop_index("ix_rag_documents_source_id", table_name="rag_documents")
    op.drop_index("ix_rag_documents_project_id", table_name="rag_documents")
    op.drop_table("rag_documents")
