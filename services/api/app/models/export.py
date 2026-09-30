"""Database model of the export trace (stage 11)."""

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


class DocumentExport(Base):
    """A record that an export was produced, with its options and the renderer's warnings.

    The generated file itself is **not** stored: it is streamed to the author and, if they
    want to keep it, they download it. This table therefore holds no memoir content, only the
    trace needed for an audit and for the "last exported" indicator.
    """

    __tablename__ = "document_exports"
    __table_args__ = (
        CheckConstraint("format IN ('pdf', 'docx')", name="ck_document_exports_format"),
        Index("ix_document_exports_project_created", "project_id", "created_at"),
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
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str] = mapped_column(String(400), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    style_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    figure_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    table_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    citation_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    uncited_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    orphan_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    options: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["DocumentExport"]
