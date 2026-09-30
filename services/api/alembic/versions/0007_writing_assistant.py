"""Add the assisted writing history and its grounded citations.

Revision ID: 0007_writing_assistant
Revises: 0006_assistant
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_writing_assistant"
down_revision: str | None = "0006_assistant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = (
    "rephrase",
    "correct",
    "academic_style",
    "summarize",
    "expand",
    "condense",
    "translate",
    "explain",
    "transition",
    "analyze_section",
    "verify_claims",
    "write_from_sources",
)


def upgrade() -> None:
    op.create_table(
        "writing_generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("instruction", sa.Text(), server_default="", nullable=False),
        sa.Column("selection_excerpt", sa.Text(), server_default="", nullable=False),
        sa.Column("proposed_text", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="completed", nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("cost_is_estimate", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("chunks_retrieved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_sources", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "rejected_citations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("grounding_note", sa.Text(), nullable=True),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("rag_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # SET NULL: deleting a section keeps the generation history readable.
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('completed', 'insufficient_sources', 'failed', 'discarded')",
            name="ck_writing_generations_status",
        ),
        sa.CheckConstraint(
            "action IN ({})".format(", ".join(f"'{value}'" for value in ACTIONS)),
            name="ck_writing_generations_action",
        ),
    )
    op.create_index("ix_writing_generations_project_id", "writing_generations", ["project_id"])
    op.create_index("ix_writing_generations_user_id", "writing_generations", ["user_id"])
    op.create_index("ix_writing_generations_section_id", "writing_generations", ["section_id"])
    op.create_index("ix_writing_generations_created_at", "writing_generations", ["created_at"])
    op.create_index(
        "ix_writing_generations_project_created",
        "writing_generations",
        ["project_id", "created_at"],
    )

    op.create_table(
        "writing_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("citation_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provenance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("rag_score", sa.Float(), nullable=False),
        sa.Column("source_title", sa.String(length=1000), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generation_id"], ["writing_generations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["rag_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["source_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["provenance_id"], ["source_blocks.provenance_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_writing_citations_generation_id", "writing_citations", ["generation_id"]
    )
    op.create_index("ix_writing_citations_project_id", "writing_citations", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_writing_citations_project_id", table_name="writing_citations")
    op.drop_index("ix_writing_citations_generation_id", table_name="writing_citations")
    op.drop_table("writing_citations")
    op.drop_index(
        "ix_writing_generations_project_created", table_name="writing_generations"
    )
    op.drop_index("ix_writing_generations_created_at", table_name="writing_generations")
    op.drop_index("ix_writing_generations_section_id", table_name="writing_generations")
    op.drop_index("ix_writing_generations_user_id", table_name="writing_generations")
    op.drop_index("ix_writing_generations_project_id", table_name="writing_generations")
    op.drop_table("writing_generations")
