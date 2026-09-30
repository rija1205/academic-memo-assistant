"""Add the document export history.

Revision ID: 0010_document_exports
Revises: 0009_citations
Create Date: 2026-10-14

An export is not written to the database: it is generated on demand and streamed. What is
stored is the *trace* of the export — who exported which project, in which format, with which
options, how large the result was, and what the renderer warned about.

That trace is what makes three things possible:

* the author sees when the last PDF was produced;
* an audit can answer "was this memoir ever exported, and by whom";
* a warning such as "3 figures could not be embedded" survives the request that produced it.

No bibliographic or document content is copied into this table, so it cannot leak a memoir.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_document_exports"
down_revision: str | None = "0009_citations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPORT_FORMATS = ("pdf", "docx")


def upgrade() -> None:
    op.create_table(
        "document_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=400), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("style", sa.String(length=64), nullable=True),
        sa.Column("style_label", sa.String(length=64), nullable=True),
        sa.Column("section_count", sa.Integer(), nullable=False),
        sa.Column("figure_count", sa.Integer(), nullable=False),
        sa.Column("table_count", sa.Integer(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("uncited_count", sa.Integer(), nullable=False),
        sa.Column("orphan_count", sa.Integer(), nullable=False),
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "options",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # The trace belongs to the project: removing a memoir removes its export history too.
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "format IN ({})".format(", ".join(f"'{value}'" for value in EXPORT_FORMATS)),
            name="ck_document_exports_format",
        ),
    )
    op.create_index(
        "ix_document_exports_project_id", "document_exports", ["project_id"]
    )
    op.create_index(
        "ix_document_exports_created_at", "document_exports", ["created_at"]
    )
    op.create_index(
        "ix_document_exports_project_created",
        "document_exports",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_exports_project_created", table_name="document_exports")
    op.drop_index("ix_document_exports_created_at", table_name="document_exports")
    op.drop_index("ix_document_exports_project_id", table_name="document_exports")
    op.drop_table("document_exports")
