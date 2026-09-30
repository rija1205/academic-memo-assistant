"""Database models for the assisted writing stage (stage 8).

``WritingGeneration`` records every proposal the model produced, whether or not the author
applied it. That history is the audit trail: the assistant proposes, the author decides.

``WritingCitation`` links a proposal to the passage it was grounded on, so a generated
paragraph can be traced back to a document and a page exactly like an answer from stage 7.

The model never writes to ``sections``. Applying a proposal goes through the existing section
save endpoint, which keeps its optimistic concurrency control and revision history.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACTIONS = (
    "rephrase",
    "correct",
    "academic_style",
    "summarize",
    "expand",
    "condense",
    "translate",
    "explain",
    "transition",
    "analyze_section",
    "verify_claims",
    "write_from_sources",
)
GENERATION_STATUSES = ("completed", "insufficient_sources", "failed", "discarded")


class WritingGeneration(Base):
    __tablename__ = "writing_generations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'insufficient_sources', 'failed', 'discarded')",
            name="ck_writing_generations_status",
        ),
        CheckConstraint(
            "action IN ({})".format(", ".join(f"'{value}'" for value in ACTIONS)),
            name="ck_writing_generations_action",
        ),
        Index("ix_writing_generations_project_created", "project_id", "created_at"),
        Index("ix_writing_generations_section", "section_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    #: Excerpt of what the author had selected, kept for context and reproducibility.
    selection_excerpt: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    proposed_text: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="completed", server_default="completed", nullable=False
    )
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    estimated_cost_usd: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0", nullable=False
    )
    cost_is_estimate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    chunks_retrieved: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    used_sources: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    rejected_citations: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    grounding_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rag_duration_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    llm_duration_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    #: Set when the author applies or discards the proposal, so history stays meaningful.
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class WritingCitation(Base):
    __tablename__ = "writing_citations"
    __table_args__ = (Index("ix_writing_citations_generation", "generation_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("writing_generations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag_chunks.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    source_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    provenance_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_blocks.provenance_id", ondelete="SET NULL"),
        nullable=True,
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    rag_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["ACTIONS", "GENERATION_STATUSES", "WritingCitation", "WritingGeneration"]
