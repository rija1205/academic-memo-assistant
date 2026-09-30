"""Add the academic audit snapshots.

Revision ID: 0011_academic_audit
Revises: 0010_document_exports
Create Date: 2026-10-21

An audit is recomputed on demand, so nothing is required to run one. What is stored is the
*trace* of each run: how many blockers, warnings and observations it found, and which ones.

Storing the trace answers a question the live report cannot: "is the memoir getting better,
or did I only get lucky once?". A student can run the audit weekly and see the blocker count
fall, which is the real signal before a deposit.

No text of the memoir is copied into this table. The findings are stored as JSON because they
are the audit's own output, not the author's content.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_academic_audit"
down_revision: str | None = "0010_document_exports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READINESS_LEVELS = ("aucun_bloquant", "corrections_requises", "reprise_necessaire")


def upgrade() -> None:
    op.create_table(
        "academic_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "readiness", sa.String(length=32), server_default="corrections_requises", nullable=False
        ),
        sa.Column("blocker_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("info_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checks_run", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checks_inconclusive", sa.Integer(), server_default="0", nullable=False),
        sa.Column("word_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("citation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reference_count", sa.Integer(), server_default="0", nullable=False),
        # The audit's own findings, stored as data. Never the memoir's text.
        sa.Column(
            "findings",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "readiness IN ({})".format(", ".join(f"'{v}'" for v in READINESS_LEVELS)),
            name="ck_academic_audits_readiness",
        ),
    )
    op.create_index("ix_academic_audits_project_id", "academic_audits", ["project_id"])
    op.create_index("ix_academic_audits_created_at", "academic_audits", ["created_at"])
    op.create_index(
        "ix_academic_audits_project_created",
        "academic_audits",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_academic_audits_project_created", table_name="academic_audits")
    op.drop_index("ix_academic_audits_created_at", table_name="academic_audits")
    op.drop_index("ix_academic_audits_project_id", table_name="academic_audits")
    op.drop_table("academic_audits")
