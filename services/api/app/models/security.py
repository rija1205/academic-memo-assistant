"""Database models for platform administration and the security log (stage 13)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SecurityEvent(Base):
    """One security-relevant event.

    The log holds an actor, a resource and an outcome. It deliberately holds **no** password,
    no token and no content of the memoir. The client address is stored hashed, so an incident
    stays attributable without turning the table into a readable history of who visited what.
    """

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('login_succeeded', 'login_failed', 'logout', 'account_suspended',"
            " 'permission_denied', 'cross_project_attempt', 'rate_limit_tripped',"
            " 'export_generated', 'bulk_action', 'admin_action')",
            name="ck_security_events_kind",
        ),
        CheckConstraint(
            "outcome IN ('success', 'failure', 'blocked')",
            name="ck_security_events_outcome",
        ),
        Index("ix_security_events_kind_created", "kind", "created_at"),
        Index("ix_security_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(16), default="success", server_default="success", nullable=False
    )
    detail: Mapped[str | None] = mapped_column(String(600), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AdminAuditEvent(Base):
    """A deliberate action by an administrator.

    Kept apart from :class:`SecurityEvent` so "what did an administrator do" is one cheap
    query instead of a filter over the whole routine log.
    """

    __tablename__ = "admin_audit_events"
    __table_args__ = (Index("ix_admin_audit_events_actor_id", "actor_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(16), default="success", server_default="success", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


__all__ = ["AdminAuditEvent", "SecurityEvent"]
