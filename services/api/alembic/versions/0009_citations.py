"""Add academic citations and the organisation flag on authors.

Revision ID: 0009_citations
Revises: 0008_bibliography
Create Date: 2026-10-07

Two changes:

* ``citations`` and ``citation_items``, which bind the Tiptap document to real entries of
  ``bibliographic_references``. No bibliographic metadata is duplicated in them;
* ``reference_authors.is_organization``, so a collective author (FAO, OMS, INSTAT) can be
  rendered as an organisation instead of being treated as a person with a surname.

The column is added with a ``false`` default, so every author created by stage 9 keeps its
meaning and no existing row needs a backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_citations"
down_revision: str | None = "0008_bibliography"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCATOR_TYPES = ("page", "pages", "chapter", "figure", "table", "section", "other")


def upgrade() -> None:
    op.add_column(
        "reference_authors",
        sa.Column(
            "is_organization",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column(
            "position_in_section", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("citation_key", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=255), nullable=True),
        sa.Column("suffix", sa.String(length=255), nullable=True),
        sa.Column("locator_type", sa.String(length=16), nullable=True),
        sa.Column("locator_value", sa.String(length=120), nullable=True),
        sa.Column(
            "mode", sa.String(length=16), server_default="parenthetical", nullable=False
        ),
        sa.Column("snapshot_style", sa.String(length=64), nullable=True),
        sa.Column("snapshot_text", sa.Text(), nullable=True),
        sa.Column(
            "snapshot_data",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_orphaned",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # A citation is document content: it disappears with its section, like the section
        # revisions already do. The historical rendering is protected by the snapshot columns.
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", name="uq_citations_node_id"),
        sa.CheckConstraint(
            "mode IN ('parenthetical', 'narrative')",
            name="ck_citations_mode",
        ),
        sa.CheckConstraint(
            "locator_type IS NULL OR locator_type IN ({})".format(
                ", ".join(f"'{value}'" for value in LOCATOR_TYPES)
            ),
            name="ck_citations_locator_type",
        ),
    )
    op.create_index("ix_citations_project_id", "citations", ["project_id"])
    op.create_index("ix_citations_section_id", "citations", ["section_id"])
    op.create_index("ix_citations_deleted_at", "citations", ["deleted_at"])
    op.create_index(
        "ix_citations_project_section", "citations", ["project_id", "section_id"]
    )
    op.create_index(
        "ix_citations_project_position", "citations", ["project_id", "position_in_section"]
    )
    # Live lookup: "which citations point at this reference?" drives the uncited list and the
    # orphan detection.
    op.create_index(
        "ix_citations_citation_key", "citations", ["project_id", "citation_key"]
    )

    op.create_table(
        "citation_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("locator_type", sa.String(length=16), nullable=True),
        sa.Column("locator_value", sa.String(length=120), nullable=True),
        sa.Column("prefix", sa.String(length=255), nullable=True),
        sa.Column("suffix", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # CASCADE: a citation item is meaningless without its citation. When the reference row
        # is hard-deleted, the snapshot of the parent citation is what keeps the history
        # readable, so nothing is lost by dropping the link.
        sa.ForeignKeyConstraint(["citation_id"], ["citations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reference_id"], ["bibliographic_references.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("citation_id", "position", name="uq_citation_items_position"),
        sa.CheckConstraint(
            "locator_type IS NULL OR locator_type IN ({})".format(
                ", ".join(f"'{value}'" for value in LOCATOR_TYPES)
            ),
            name="ck_citation_items_locator_type",
        ),
    )
    op.create_index("ix_citation_items_citation_id", "citation_items", ["citation_id"])
    op.create_index("ix_citation_items_reference_id", "citation_items", ["reference_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_items_reference_id", table_name="citation_items")
    op.drop_index("ix_citation_items_citation_id", table_name="citation_items")
    op.drop_table("citation_items")
    op.drop_index("ix_citations_citation_key", table_name="citations")
    op.drop_index("ix_citations_project_position", table_name="citations")
    op.drop_index("ix_citations_project_section", table_name="citations")
    op.drop_index("ix_citations_deleted_at", table_name="citations")
    op.drop_index("ix_citations_section_id", table_name="citations")
    op.drop_index("ix_citations_project_id", table_name="citations")
    op.drop_table("citations")
    op.drop_column("reference_authors", "is_organization")
