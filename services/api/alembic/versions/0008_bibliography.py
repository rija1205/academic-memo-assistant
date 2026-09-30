"""Add the bibliography: references, authors, tags and tag links.

Revision ID: 0008_bibliography
Revises: 0007_writing_assistant
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_bibliography"
down_revision: str | None = "0007_writing_assistant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFERENCE_TYPES = (
    "article",
    "book",
    "book_chapter",
    "thesis",
    "report",
    "conference",
    "webpage",
    "dataset",
    "patent",
    "other",
)


def upgrade() -> None:
    op.create_table(
        "bibliographic_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_key", sa.String(length=200), nullable=False),
        sa.Column("reference_type", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("subtitle", sa.String(length=1000), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("publication_month", sa.String(length=16), nullable=True),
        sa.Column("publication_day", sa.String(length=16), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("doi_original", sa.String(length=500), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("accessed_at", sa.Date(), nullable=True),
        sa.Column("journal", sa.String(length=500), nullable=True),
        sa.Column("volume", sa.String(length=64), nullable=True),
        sa.Column("issue", sa.String(length=64), nullable=True),
        sa.Column("pages", sa.String(length=128), nullable=True),
        sa.Column("publisher", sa.String(length=500), nullable=True),
        sa.Column("publisher_place", sa.String(length=255), nullable=True),
        sa.Column("edition", sa.String(length=64), nullable=True),
        sa.Column("isbn", sa.String(length=64), nullable=True),
        sa.Column("issn", sa.String(length=64), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column(
            "keywords",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "extra_fields",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        # SET NULL: deleting the imported file keeps the bibliographic record usable.
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "citation_key", name="uq_bibliographic_citation_key"
        ),
        sa.CheckConstraint(
            "reference_type IN ({})".format(
                ", ".join(f"'{value}'" for value in REFERENCE_TYPES)
            ),
            name="ck_bibliographic_references_type",
        ),
    )
    op.create_index(
        "ix_bibliographic_references_project_id", "bibliographic_references", ["project_id"]
    )
    op.create_index(
        "ix_bibliographic_references_source_id", "bibliographic_references", ["source_id"]
    )
    op.create_index(
        "ix_bibliographic_references_deleted_at", "bibliographic_references", ["deleted_at"]
    )
    op.create_index(
        "ix_bibliographic_references_project_year",
        "bibliographic_references",
        ["project_id", "publication_year"],
    )
    op.create_index(
        "ix_bibliographic_references_doi", "bibliographic_references", ["project_id", "doi"]
    )    # Full-text search over the bibliographic fields, independent of the RAG index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bibliographic_references_search "
        "ON bibliographic_references USING gin ("
        "to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(journal,'') || ' ' || "
        "coalesce(doi,'') || ' ' || coalesce(abstract,'')))"
    )

    op.create_table(
        "reference_authors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("given_name", sa.String(length=200), nullable=True),
        sa.Column("family_name", sa.String(length=200), nullable=False),
        sa.Column("orcid", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["reference_id"], ["bibliographic_references.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id", "position", name="uq_reference_authors_position"),
    )
    op.create_index("ix_reference_authors_reference_id", "reference_authors", ["reference_id"])
    op.create_index("ix_reference_authors_family_name", "reference_authors", ["family_name"])

    op.create_table(
        "reference_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "normalized_name", name="uq_reference_tags_project_name"),
    )
    op.create_index("ix_reference_tags_project_id", "reference_tags", ["project_id"])

    op.create_table(
        "reference_tag_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reference_id"], ["bibliographic_references.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["reference_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id", "tag_id", name="uq_reference_tag_links"),
    )
    op.create_index("ix_reference_tag_links_reference_id", "reference_tag_links", ["reference_id"])
    op.create_index("ix_reference_tag_links_tag_id", "reference_tag_links", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_reference_tag_links_tag_id", table_name="reference_tag_links")
    op.drop_index("ix_reference_tag_links_reference_id", table_name="reference_tag_links")
    op.drop_table("reference_tag_links")
    op.drop_index("ix_reference_tags_project_id", table_name="reference_tags")
    op.drop_table("reference_tags")
    op.drop_index("ix_reference_authors_family_name", table_name="reference_authors")
    op.drop_index("ix_reference_authors_reference_id", table_name="reference_authors")
    op.drop_table("reference_authors")
    op.execute("DROP INDEX IF EXISTS ix_bibliographic_references_search")
    op.drop_index("ix_bibliographic_references_doi", table_name="bibliographic_references")
    op.drop_index(
        "ix_bibliographic_references_project_year", table_name="bibliographic_references"
    )
    op.drop_index(
        "ix_bibliographic_references_deleted_at", table_name="bibliographic_references"
    )
    op.drop_index("ix_bibliographic_references_source_id", table_name="bibliographic_references")
    op.drop_index("ix_bibliographic_references_project_id", table_name="bibliographic_references")
    op.drop_table("bibliographic_references")
