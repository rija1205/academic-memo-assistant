from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourceStatus = Literal["uploaded", "processing", "processed", "failed"]
SourceStage = Literal["queued", "validating", "extracting", "ocr", "enriching", "done", "failed"]
PublicationType = Literal[
    "article",
    "book",
    "book_chapter",
    "thesis",
    "memo",
    "report",
    "conference",
    "website",
    "other",
]


class SourceResponse(BaseModel):
    id: UUID
    project_id: UUID
    folder_id: UUID | None
    original_filename: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: SourceStatus
    stage: SourceStage
    progress: int
    error_message: str | None
    title: str | None
    authors: list[str]
    publication_year: int | None
    doi: str | None
    url: str | None
    journal: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    publisher: str | None
    publication_type: PublicationType
    abstract: str | None
    keywords: list[str]
    detected_language: str | None
    page_count: int | None
    imported_at: datetime
    created_at: datetime
    updated_at: datetime
    tags: list[str] = Field(default_factory=list)
    duplicate_of: UUID | None = None
    duplicate_reason: str | None = None
    job_id: UUID | None = None


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    total: int
    limit: int
    offset: int


class SourceMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=1000)
    authors: list[str] | None = None
    publication_year: int | None = Field(default=None, ge=1000, le=3000)
    doi: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=4000)
    journal: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=64)
    issue: str | None = Field(default=None, max_length=64)
    pages: str | None = Field(default=None, max_length=128)
    publisher: str | None = Field(default=None, max_length=500)
    publication_type: PublicationType | None = None
    abstract: str | None = Field(default=None, max_length=20000)
    keywords: list[str] | None = None
    folder_id: UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=50)


class SourcePageResponse(BaseModel):
    id: UUID
    source_id: UUID
    page_number: int
    text: str
    char_count: int
    blocks: list["SourceBlockResponse"] = Field(default_factory=list)


class SourceBlockResponse(BaseModel):
    id: UUID
    source_id: UUID
    page_id: UUID | None
    page_number: int
    block_index: int
    block_type: str
    text: str
    position_start: int
    position_end: int
    provenance_id: UUID


class SourcePreviewResponse(BaseModel):
    source: SourceResponse
    pages: list[SourcePageResponse]
    warnings: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    sheets: list[str] = Field(default_factory=list)


class SourceSearchResult(BaseModel):
    source_id: UUID
    source_title: str
    original_filename: str
    page_number: int
    block_index: int
    provenance_id: UUID
    snippet: str
    match_start: int
    match_end: int


class SourceSearchResponse(BaseModel):
    query: str
    results: list[SourceSearchResult]
    total: int


class SourceFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SourceFolderResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    created_at: datetime
    source_count: int = 0


class SourceJobResponse(BaseModel):
    id: UUID
    source_id: UUID
    task_id: str | None
    status: Literal["queued", "running", "completed", "failed"]
    stage: str
    progress: int
    attempts: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceDuplicateResponse(BaseModel):
    source_id: UUID
    sha256: str
    title: str | None
    reason: str


class SourceUploadResponse(BaseModel):
    source: SourceResponse
    duplicate: SourceDuplicateResponse | None = None


SourcePageResponse.model_rebuild()
