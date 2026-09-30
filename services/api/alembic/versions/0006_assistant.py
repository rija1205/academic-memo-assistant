"""Add the academic assistant: conversations, messages and grounded citations.

Revision ID: 0006_assistant
Revises: 0005_academic_rag
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_assistant"
down_revision: str | None = "0005_academic_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_conversations_project_id", "assistant_conversations", ["project_id"]
    )
    op.create_index(
        "ix_assistant_conversations_user_id", "assistant_conversations", ["user_id"]
    )
    op.create_index(
        "ix_assistant_conversations_deleted_at", "assistant_conversations", ["deleted_at"]
    )
    op.create_index(
        "ix_assistant_conversations_project_updated",
        "assistant_conversations",
        ["project_id", "updated_at"],
    )

    op.create_table(
        "assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "cost_is_estimate", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("rag_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_retrieved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("grounding_note", sa.Text(), nullable=True),
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
            ["conversation_id"], ["assistant_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_assistant_messages_sequence"
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_assistant_messages_role"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'insufficient_sources', 'failed')",
            name="ck_assistant_messages_status",
        ),
    )
    op.create_index(
        "ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id"]
    )
    op.create_index("ix_assistant_messages_project_id", "assistant_messages", ["project_id"])
    op.create_index("ix_assistant_messages_created_at", "assistant_messages", ["created_at"])
    op.create_index(
        "ix_assistant_messages_conversation_created",
        "assistant_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "assistant_citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["message_id"], ["assistant_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["assistant_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        # A citation keeps pointing at a readable provenance even if the chunk is re-indexed.
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["rag_chunks.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["source_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["provenance_id"], ["source_blocks.provenance_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "position", name="uq_assistant_citations_position"),
    )
    op.create_index("ix_assistant_citations_message_id", "assistant_citations", ["message_id"])
    op.create_index(
        "ix_assistant_citations_conversation_id", "assistant_citations", ["conversation_id"]
    )
    op.create_index("ix_assistant_citations_project_id", "assistant_citations", ["project_id"])
    op.create_index("ix_assistant_citations_source_id", "assistant_citations", ["source_id"])
    op.create_index("ix_assistant_citations_chunk_id", "assistant_citations", ["chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_citations_chunk_id", table_name="assistant_citations")
    op.drop_index("ix_assistant_citations_source_id", table_name="assistant_citations")
    op.drop_index("ix_assistant_citations_project_id", table_name="assistant_citations")
    op.drop_index(
        "ix_assistant_citations_conversation_id", table_name="assistant_citations"
    )
    op.drop_index("ix_assistant_citations_message_id", table_name="assistant_citations")
    op.drop_table("assistant_citations")

    op.drop_index(
        "ix_assistant_messages_conversation_created", table_name="assistant_messages"
    )
    op.drop_index("ix_assistant_messages_created_at", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_project_id", table_name="assistant_messages")
    op.drop_index(
        "ix_assistant_messages_conversation_id", table_name="assistant_messages"
    )
    op.drop_table("assistant_messages")

    op.drop_index(
        "ix_assistant_conversations_project_updated", table_name="assistant_conversations"
    )
    op.drop_index(
        "ix_assistant_conversations_deleted_at", table_name="assistant_conversations"
    )
    op.drop_index("ix_assistant_conversations_user_id", table_name="assistant_conversations")
    op.drop_index(
        "ix_assistant_conversations_project_id", table_name="assistant_conversations"
    )
    op.drop_table("assistant_conversations")
