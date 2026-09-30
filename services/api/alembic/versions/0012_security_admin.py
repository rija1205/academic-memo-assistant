"""Add platform administration and the security event log.

Revision ID: 0012_security_admin
Revises: 0011_academic_audit
Create Date: 2026-10-28

Three changes:

* ``users.is_admin``, ``users.is_suspended``, ``users.suspended_at``,
  ``users.suspended_reason``, ``users.last_login_at``. All with a neutral default, so every
  existing account keeps exactly the rights it had: **no account is an administrator by
  accident**, because the first row created is no more privileged than the thousandth.
* ``security_events``, an append-only log of what happened. It holds an actor, a resource and
  an outcome — never a password, a token or the author's text.
* ``admin_audit_events``, the deliberate actions of an administrator, kept apart from the
  routine events so an operator can answer "what did an administrator do" in one query.

The security log is written with ``ON DELETE CASCADE`` on the user, so removing an account
removes its trail along with it, as the right to be forgotten requires.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_security_admin"
down_revision: str | None = "0011_academic_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_KINDS = (
    "login_succeeded",
    "login_failed",
    "logout",
    "account_suspended",
    "permission_denied",
    "cross_project_attempt",
    "rate_limit_tripped",
    "export_generated",
    "bulk_action",
    "admin_action",
)

OUTCOMES = ("success", "failure", "blocked")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_suspended",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("suspended_reason", sa.String(length=400), nullable=True)
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_is_suspended", "users", ["is_suspended"])

    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("resource", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=16), server_default="success", nullable=False),
        sa.Column("detail", sa.String(length=600), nullable=True),
        # The address is stored hashed: an incident needs to be attributable, and the log
        # should not become a readable list of who visited what.
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ({})".format(", ".join(f"'{value}'" for value in EVENT_KINDS)),
            name="ck_security_events_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ({})".format(", ".join(f"'{value}'" for value in OUTCOMES)),
            name="ck_security_events_outcome",
        ),
    )
    op.create_index("ix_security_events_user_id", "security_events", ["user_id"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])
    op.create_index(
        "ix_security_events_kind_created", "security_events", ["kind", "created_at"]
    )
    op.create_index(
        "ix_security_events_user_created", "security_events", ["user_id", "created_at"]
    )

    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.String(length=400), nullable=True),
        sa.Column("outcome", sa.String(length=16), server_default="success", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_events_actor_id", "admin_audit_events", ["actor_id"])
    op.create_index(
        "ix_admin_audit_events_created_at", "admin_audit_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_events_created_at", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_events_actor_id", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
    op.drop_index("ix_security_events_user_created", table_name="security_events")
    op.drop_index("ix_security_events_kind_created", table_name="security_events")
    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_user_id", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("ix_users_is_suspended", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "is_suspended")
    op.drop_column("users", "is_admin")
