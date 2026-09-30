"""Database model of an audit run (stage 12)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AcademicAudit(Base):
    """The trace of one audit run.

    The findings are stored as JSON because they are the audit's own output. The memoir's text
    is never copied here, so this table cannot leak its content.
    """

    __tablename__ = "academic_audits"
    __table_args__ = (
        CheckConstraint(
            "readiness IN ('aucun_bloquant', 'corrections_requises', 'reprise_necessaire')",
            name="ck_academic_audits_readiness",
        ),
        Index("ix_academic_audits_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    readiness: Mapped[str] = mapped_column(
        String(32),
        default="corrections_requises",
        server_default="corrections_requises",
        nullable=False,
    )
    blocker_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    warning_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    info_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    checks_run: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    checks_inconclusive: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    word_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    citation_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reference_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    findings: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["AcademicAudit"]
