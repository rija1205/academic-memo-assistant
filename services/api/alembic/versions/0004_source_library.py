"""Add the source library, files, extraction provenance and processing jobs.

Revision ID: 0004_source_library
Revises: 0003_project_workspace
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_source_library"
down_revision: str | None = "0003_project_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "normalized_name", name="uq_source_folders_project_name"
        ),
    )
    op.create_index("ix_source_folders_project_id", "source_folders", ["project_id"])

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="uploaded", nullable=False),
        sa.Column("stage", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column(
            "authors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("journal", sa.String(length=500), nullable=True),
        sa.Column("volume", sa.String(length=64), nullable=True),
        sa.Column("issue", sa.String(length=64), nullable=True),
        sa.Column("pages", sa.String(length=128), nullable=True),
        sa.Column("publisher", sa.String(length=500), nullable=True),
        sa.Column(
            "publication_type",
            sa.String(length=64),
            server_default="other",
            nullable=False,
        ),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column(
            "keywords",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("detected_language", sa.String(length=32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["folder_id"], ["source_folders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'failed')",
            name="ck_sources_status",
        ),
        sa.CheckConstraint(
            "stage IN ('queued', 'validating', 'extracting', 'ocr', 'enriching', 'done', 'failed')",
            name="ck_sources_stage",
        ),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("ix_sources_uploaded_by", "sources", ["uploaded_by"])
    op.create_index("ix_sources_folder_id", "sources", ["folder_id"])
    op.create_index("ix_sources_doi", "sources", ["doi"])
    op.create_index("ix_sources_deleted_at", "sources", ["deleted_at"])
    op.create_index("ix_sources_project_status", "sources", ["project_id", "status"])
    op.create_index("ix_sources_project_sha256", "sources", ["project_id", "sha256"])

    op.create_table(
        "source_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_provider", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_source_files_source"),
    )
    op.create_index("ix_source_files_source_id", "source_files", ["source_id"])

    op.create_table(
        "source_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "page_number", name="uq_source_pages_source_page"),
    )
    op.create_index("ix_source_pages_source_id", "source_pages", ["source_id"])

    op.create_table(
        "source_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("position_start", sa.Integer(), server_default="0", nullable=False),
        sa.Column("position_end", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provenance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["source_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "page_number", "block_index", name="uq_source_blocks_order"
        ),
        sa.UniqueConstraint("provenance_id", name="uq_source_blocks_provenance"),
    )
    op.create_index("ix_source_blocks_source_id", "source_blocks", ["source_id"])
    op.create_index("ix_source_blocks_page_id", "source_blocks", ["page_id"])
    op.create_index(
        "ix_source_blocks_search", "source_blocks", ["source_id", "page_number", "block_index"]
    )

    op.create_table(
        "source_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "normalized_name", name="uq_source_tags_source_name"),
    )
    op.create_index("ix_source_tags_source_id", "source_tags", ["source_id"])
    op.create_index("ix_source_tags_project_id", "source_tags", ["project_id"])
    op.create_index(
        "ix_source_tags_project_name", "source_tags", ["project_id", "normalized_name"]
    )

    op.create_table(
        "source_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_source_processing_jobs_status",
        ),
    )
    op.create_index(
        "ix_source_processing_jobs_source_id", "source_processing_jobs", ["source_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_processing_jobs_source_id", table_name="source_processing_jobs")
    op.drop_table("source_processing_jobs")
    op.drop_index("ix_source_tags_project_name", table_name="source_tags")
    op.drop_index("ix_source_tags_project_id", table_name="source_tags")
    op.drop_index("ix_source_tags_source_id", table_name="source_tags")
    op.drop_table("source_tags")
    op.drop_index("ix_source_blocks_search", table_name="source_blocks")
    op.drop_index("ix_source_blocks_page_id", table_name="source_blocks")
    op.drop_index("ix_source_blocks_source_id", table_name="source_blocks")
    op.drop_table("source_blocks")
    op.drop_index("ix_source_pages_source_id", table_name="source_pages")
    op.drop_table("source_pages")
    op.drop_index("ix_source_files_source_id", table_name="source_files")
    op.drop_table("source_files")
    op.drop_index("ix_sources_project_sha256", table_name="sources")
    op.drop_index("ix_sources_project_status", table_name="sources")
    op.drop_index("ix_sources_deleted_at", table_name="sources")
    op.drop_index("ix_sources_doi", table_name="sources")
    op.drop_index("ix_sources_folder_id", table_name="sources")
    op.drop_index("ix_sources_uploaded_by", table_name="sources")
    op.drop_index("ix_sources_project_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_source_folders_project_id", table_name="source_folders")
    op.drop_table("source_folders")
