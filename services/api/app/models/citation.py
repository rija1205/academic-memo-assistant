"""Database models for academic citations (stage 10).

Design rules that the rest of the application depends on:

* **The rendered text is never the source of truth.** A row stores the identity of the
  references it points to (``citation_items.reference_id``) and nothing bibliographic. A style
  change or a metadata correction is therefore reflected everywhere at once, with no data
  migration: ``Dupont, 2024`` becomes ``Dupont, 2025`` because the year is read from the
  reference at render time.
* **Snapshots exist only for history.** ``snapshot_text`` freezes what a citation looked like
  when it was written, so that reading an old revision still shows the citation the author
  actually wrote even if the reference has since been deleted. It is never used for the
  current document.
* **A citation is document content.** It belongs to a section and cascades with it, exactly
  like the section revisions that already do. A reference, on the other hand, is a library
  record: deleting a citation must never delete the reference it pointed to.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

LOCATOR_TYPES = ("page", "pages", "chapter", "figure", "table", "section", "other")
CITATION_MODES = ("parenthetical", "narrative")


class Citation(Base):
    """One citation node of the document, which may point to several references."""

    __tablename__ = "citations"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('parenthetical', 'narrative')",
            name="ck_citations_mode",
        ),
        Index("ix_citations_project_section", "project_id", "section_id"),
        Index("ix_citations_project_position", "project_id", "position_in_section"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    section_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Stable token carried by the Tiptap node, so the document can be matched to the rows.
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Order of the citation inside its section, used to compute document order.
    position_in_section: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    #: Internal key, human readable in logs and stable across a rename of the node.
    citation_key: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Default locator applied to every item that does not carry its own.
    locator_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    locator_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(16), default="parenthetical", server_default="parenthetical", nullable=False
    )
    #: Style that produced ``snapshot_text``, so a history entry can explain itself.
    snapshot_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Frozen rendering, used only when reading an old revision or a deleted reference.
    snapshot_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The bibliographic facts behind the snapshot, so a lost reference is still explainable.
    snapshot_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    #: True when at least one referenced reference was removed; the citation is then invalid.
    is_orphaned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )


class CitationItem(Base):
    """One reference inside a citation, with its own locator and affixes."""

    __tablename__ = "citation_items"
    __table_args__ = (
        UniqueConstraint("citation_id", "position", name="uq_citation_items_position"),
        CheckConstraint(
            "locator_type IS NULL OR locator_type IN ({})".format(
                ", ".join(f"'{value}'" for value in LOCATOR_TYPES)
            ),
            name="ck_citation_items_locator_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    citation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("citations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: The canonical link. CASCADE is safe because the snapshot of the parent citation keeps
    #: the historical rendering even if the reference row itself disappears.
    reference_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Order of the reference inside the citation.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    locator_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    locator_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suffix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["CITATION_MODES", "LOCATOR_TYPES", "Citation", "CitationItem"]
