"""Database models for the bibliography (stage 9).

Structure:

* ``BibliographicReference`` holds the record itself. A reference is a **logical** work and
  can exist without any file, which is the normal case for a work cited but not downloaded.
* ``ReferenceAuthor`` stores authors relationally because their order is data, and a given
  name, a family name and an ORCID are three different facts.
* ``ReferenceTag`` and ``ReferenceTagLink`` provide project-scoped tags.

A reference may be linked to an imported ``Source`` (the file the user downloaded), but the
link is optional and one-way: importing a file does **not** create a reference, and a
reference does **not** copy the source metadata. The link avoids storing the same facts twice,
and an absent metadata field stays ``NULL`` rather than being invented.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class BibliographicReference(Base):
    __tablename__ = "bibliographic_references"
    __table_args__ = (
        UniqueConstraint("project_id", "citation_key", name="uq_bibliographic_citation_key"),
        CheckConstraint(
            "reference_type IN ({})".format(
                ", ".join(f"'{value}'" for value in REFERENCE_TYPES)
            ),
            name="ck_bibliographic_references_type",
        ),
        Index("ix_bibliographic_references_project_year", "project_id", "publication_year"),
        Index("ix_bibliographic_references_doi", "project_id", "doi"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: Stable key used by styles in the next stage (e.g. ``dupont2024``).
    citation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Original BibTeX/RIS entry type, kept so an unknown type is not lost.
    entry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subtitle: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publication_month: Mapped[str | None] = mapped_column(String(16), nullable=True)
    publication_day: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Canonical DOI, used for comparison and duplicate detection.
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Exactly what the user typed or what the import file contained.
    doi_original: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    accessed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    volume: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pages: Mapped[str | None] = mapped_column(String(128), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher_place: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Fields the application does not model but the import file carried.
    extra_fields: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    #: Optional link to an imported source. ``SET NULL`` keeps the reference if the file is
    #: removed, because the bibliographic record is independent from the file.
    source_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
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


class ReferenceAuthor(Base):
    __tablename__ = "reference_authors"
    __table_args__ = (
        UniqueConstraint("reference_id", "position", name="uq_reference_authors_position"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    reference_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: 1-based position. The order of authors is part of the data.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    given_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    family_name: Mapped[str] = mapped_column(String(200), nullable=False)
    orcid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: True for a collective author (FAO, OMS, INSTAT). Added in stage 10 so a style can write
    #: ``FAO (2024)`` without guessing from the spelling or inventing initials. An existing row
    #: stays ``false``, which keeps every person of stage 9 a person.
    is_organization: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )


class ReferenceTag(Base):
    __tablename__ = "reference_tags"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_name", name="uq_reference_tags_project_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReferenceTagLink(Base):
    __tablename__ = "reference_tag_links"
    __table_args__ = (
        UniqueConstraint("reference_id", "tag_id", name="uq_reference_tag_links"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    reference_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tag_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reference_tags.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )


__all__ = [
    "REFERENCE_TYPES",
    "BibliographicReference",
    "ReferenceAuthor",
    "ReferenceTag",
    "ReferenceTagLink",
]
