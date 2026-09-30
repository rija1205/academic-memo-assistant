"""Add project workspace metadata, outline, sections and revisions.

Revision ID: 0003_project_workspace
Revises: 0002_authentication_and_sessions
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_project_workspace"
down_revision: str | None = "0002_authentication_and_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("institution", sa.String(length=255), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "education_level",
            sa.String(length=32),
            server_default="other",
            nullable=False,
        ),
    )
    op.add_column("projects", sa.Column("author_name", sa.String(length=200), nullable=True))
    op.add_column(
        "projects", sa.Column("supervisor_name", sa.String(length=200), nullable=True)
    )
    op.add_column("projects", sa.Column("academic_year", sa.String(length=32), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "thesis_type",
            sa.String(length=64),
            server_default="academic",
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "bibliography_style",
            sa.String(length=64),
            server_default="apa",
            nullable=False,
        ),
    )
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE projects "
        "SET status = 'draft' "
        "WHERE status NOT IN ('draft', 'in_progress', 'completed', 'archived')"
    )
    op.create_check_constraint(
        "ck_projects_status",
        "projects",
        "status IN ('draft', 'in_progress', 'completed', 'archived')",
    )
    op.create_check_constraint(
        "ck_projects_education_level",
        "projects",
        "education_level IN ('licence', 'master', 'doctorat', 'other')",
    )
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])

    op.create_table(
        "outline_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=16), server_default="section", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["outline_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('section', 'subsection')", name="ck_outline_nodes_kind"),
    )
    op.create_index("ix_outline_nodes_project_id", "outline_nodes", ["project_id"])
    op.create_index("ix_outline_nodes_parent_id", "outline_nodes", ["parent_id"])
    op.create_index(
        "ix_outline_nodes_project_position", "outline_nodes", ["project_id", "position"]
    )

    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outline_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(),
            server_default=sa.text(
                '\'{"type":"doc","content":[{"type":"paragraph"}]}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column("plain_text", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="empty", nullable=False),
        sa.Column("word_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_saved_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_node_id"], ["outline_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_saved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outline_node_id", name="uq_sections_outline_node"),
        sa.CheckConstraint(
            "status IN ('empty', 'in_progress', 'complete')",
            name="ck_sections_status",
        ),
    )
    op.create_index("ix_sections_project_id", "sections", ["project_id"])
    op.create_index("ix_sections_outline_node_id", "sections", ["outline_node_id"])

    op.create_table(
        "section_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("plain_text", sa.Text(), server_default="", nullable=False),
        sa.Column("word_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="in_progress",
            nullable=False,
        ),
        sa.Column("change_summary", sa.String(length=500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("restored_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["restored_from_id"], ["section_revisions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "version", name="uq_section_revisions_version"),
        sa.CheckConstraint(
            "status IN ('empty', 'in_progress', 'complete')",
            name="ck_section_revisions_status",
        ),
    )
    op.create_index("ix_section_revisions_project_id", "section_revisions", ["project_id"])
    op.create_index("ix_section_revisions_section_id", "section_revisions", ["section_id"])
    op.create_index(
        "ix_section_revisions_section_created",
        "section_revisions",
        ["section_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_section_revisions_section_created", table_name="section_revisions")
    op.drop_index("ix_section_revisions_section_id", table_name="section_revisions")
    op.drop_index("ix_section_revisions_project_id", table_name="section_revisions")
    op.drop_table("section_revisions")
    op.drop_index("ix_sections_outline_node_id", table_name="sections")
    op.drop_index("ix_sections_project_id", table_name="sections")
    op.drop_table("sections")
    op.drop_index("ix_outline_nodes_project_position", table_name="outline_nodes")
    op.drop_index("ix_outline_nodes_parent_id", table_name="outline_nodes")
    op.drop_index("ix_outline_nodes_project_id", table_name="outline_nodes")
    op.drop_table("outline_nodes")
    op.drop_index("ix_projects_deleted_at", table_name="projects")
    op.drop_constraint("ck_projects_education_level", "projects", type_="check")
    op.drop_constraint("ck_projects_status", "projects", type_="check")
    op.drop_column("projects", "archived_at")
    op.drop_column("projects", "deleted_at")
    op.drop_column("projects", "bibliography_style")
    op.drop_column("projects", "thesis_type")
    op.drop_column("projects", "academic_year")
    op.drop_column("projects", "supervisor_name")
    op.drop_column("projects", "author_name")
    op.drop_column("projects", "education_level")
    op.drop_column("projects", "institution")
