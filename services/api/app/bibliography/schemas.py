"""Pydantic contracts of the bibliography API.

Field limits are enforced here so an oversized value is rejected with a clear message rather
than truncated silently.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.bibliography.duplicates import DuplicateLevel
from app.bibliography.parsers import REFERENCE_TYPES

ReferenceType = Literal[
    "article", "book", "book_chapter", "thesis", "report", "conference", "webpage", "dataset",
    "patent", "other",
]

MAX_TITLE = 1000
MAX_ABSTRACT = 20000
MAX_NOTES = 10000
MAX_KEYWORDS = 50
MAX_AUTHORS = 200
MAX_TAGS = 50


class AuthorInput(BaseModel):
    given_name: str | None = Field(default=None, max_length=200)
    family_name: str = Field(min_length=1, max_length=200)
    orcid: str | None = Field(default=None, max_length=32)

    @field_validator("given_name", "family_name", "orcid")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReferenceCreateRequest(BaseModel):
    citation_key: str | None = Field(default=None, max_length=200)
    reference_type: ReferenceType = "other"
    entry_type: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    subtitle: str | None = Field(default=None, max_length=MAX_TITLE)
    authors: list[AuthorInput] = Field(default_factory=list, max_length=MAX_AUTHORS)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)
    publication_month: str | None = Field(default=None, max_length=16)
    publication_day: str | None = Field(default=None, max_length=16)
    doi: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=4000)
    accessed_at: date | None = None
    journal: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=64)
    issue: str | None = Field(default=None, max_length=64)
    pages: str | None = Field(default=None, max_length=128)
    publisher: str | None = Field(default=None, max_length=500)
    publisher_place: str | None = Field(default=None, max_length=255)
    edition: str | None = Field(default=None, max_length=64)
    isbn: str | None = Field(default=None, max_length=64)
    issn: str | None = Field(default=None, max_length=64)
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT)
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    language: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=MAX_NOTES)
    source_id: UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator(
        "title", "subtitle", "journal", "publisher", "publisher_place", "volume", "issue",
        "pages", "edition", "isbn", "issn", "language", "notes", "citation_key", "entry_type",
        "publication_month", "publication_day", "abstract", "url", "doi",
    )
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("keywords", "tags")
    @classmethod
    def _clean_list(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]


class ReferenceUpdateRequest(BaseModel):
    """Partial update. Only the fields present in the request are modified."""

    citation_key: str | None = Field(default=None, max_length=200)
    reference_type: ReferenceType | None = None
    entry_type: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    subtitle: str | None = Field(default=None, max_length=MAX_TITLE)
    authors: list[AuthorInput] | None = Field(default=None, max_length=MAX_AUTHORS)
    publication_year: int | None = Field(default=None, ge=1000, le=3000)
    publication_month: str | None = Field(default=None, max_length=16)
    publication_day: str | None = Field(default=None, max_length=16)
    doi: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=4000)
    accessed_at: date | None = None
    journal: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=64)
    issue: str | None = Field(default=None, max_length=64)
    pages: str | None = Field(default=None, max_length=128)
    publisher: str | None = Field(default=None, max_length=500)
    publisher_place: str | None = Field(default=None, max_length=255)
    edition: str | None = Field(default=None, max_length=64)
    isbn: str | None = Field(default=None, max_length=64)
    issn: str | None = Field(default=None, max_length=64)
    abstract: str | None = Field(default=None, max_length=MAX_ABSTRACT)
    keywords: list[str] | None = Field(default=None, max_length=MAX_KEYWORDS)
    language: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=MAX_NOTES)
    source_id: UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)


class AuthorResponse(BaseModel):
    position: int
    given_name: str | None
    family_name: str
    orcid: str | None


class DuplicateMatchResponse(BaseModel):
    reference_id: UUID
    citation_key: str
    title: str | None
    level: DuplicateLevel
    reason: str
    title_similarity: float
    shared_authors: list[str]


class DuplicateReportResponse(BaseModel):
    has_duplicates: bool
    exact: list[DuplicateMatchResponse]
    strong: list[DuplicateMatchResponse]
    possible: list[DuplicateMatchResponse]


class ReferenceResponse(BaseModel):
    id: UUID
    project_id: UUID
    citation_key: str
    reference_type: ReferenceType
    entry_type: str | None
    title: str | None
    subtitle: str | None
    authors: list[AuthorResponse]
    publication_year: int | None
    publication_month: str | None
    publication_day: str | None
    doi: str | None
    doi_original: str | None
    url: str | None
    accessed_at: date | None
    journal: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    publisher: str | None
    publisher_place: str | None
    edition: str | None
    isbn: str | None
    issn: str | None
    abstract: str | None
    keywords: list[str]
    language: str | None
    notes: str | None
    extra_fields: dict[str, str]
    source_id: UUID | None
    source_title: str | None
    tags: list[str]
    has_source: bool
    created_at: datetime
    updated_at: datetime
    missing_fields: list[str] = Field(default_factory=list)


class ReferenceListResponse(BaseModel):
    items: list[ReferenceResponse]
    total: int
    limit: int
    offset: int


class ReferenceStatsResponse(BaseModel):
    total: int
    by_type: dict[str, int]
    with_doi: int
    with_source: int
    with_url: int
    with_abstract: int
    by_year: dict[str, int]


class ImportErrorItem(BaseModel):
    message: str
    citation_key: str | None = None


class ImportResponse(BaseModel):
    imported: int
    skipped: int
    duplicates: int
    errors: list[ImportErrorItem]
    references: list[ReferenceResponse]


ExportFormat = Literal["bibtex", "ris"]


class MergeRequest(BaseModel):
    """Merge a duplicate into a target reference without losing data."""

    keep_reference_id: UUID


__all__ = [
    "MAX_ABSTRACT",
    "MAX_AUTHORS",
    "MAX_KEYWORDS",
    "MAX_NOTES",
    "MAX_TAGS",
    "MAX_TITLE",
    "REFERENCE_TYPES",
    "AuthorInput",
    "AuthorResponse",
    "DuplicateMatchResponse",
    "DuplicateReportResponse",
    "ImportErrorItem",
    "ExportFormat",
    "ImportResponse",
    "MergeRequest",
    "ReferenceCreateRequest",
    "ReferenceListResponse",
    "ReferenceResponse",
    "ReferenceStatsResponse",
    "ReferenceType",
    "ReferenceUpdateRequest",
]
