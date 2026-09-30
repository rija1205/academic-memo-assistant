"""Pydantic contracts of the export API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.export.options import EXPORT_FORMATS, PAGE_SIZES, PDF_FONTS

ExportFormat = Literal["pdf", "docx"]


class ExportOptionsRequest(BaseModel):
    """The presentation options an author may choose.

    Every field is optional; the defaults in :mod:`app.export.options` are the ones a French
    university expects. Unknown keys are ignored by the validator so a newer client still
    works against an older server.
    """

    page_size: str | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    margin_top: float | None = Field(default=None, ge=0.5, le=8.0)
    margin_bottom: float | None = Field(default=None, ge=0.5, le=8.0)
    margin_left: float | None = Field(default=None, ge=0.5, le=8.0)
    margin_right: float | None = Field(default=None, ge=0.5, le=8.0)
    font_family: str | None = None
    font_size: float | None = Field(default=None, ge=6.0, le=24.0)
    line_spacing: float | None = Field(default=None, ge=1.0, le=3.0)
    first_line_indent: float | None = Field(default=None, ge=0.0, le=5.0)
    paragraph_alignment: Literal["left", "center", "right", "justify"] | None = None
    paragraph_space_after: float | None = Field(default=None, ge=0.0, le=5.0)
    include_cover: bool | None = None
    include_toc: bool | None = None
    include_list_of_figures: bool | None = None
    include_list_of_tables: bool | None = None
    include_bibliography: bool | None = None
    include_annexes: bool | None = None
    include_page_numbers: bool | None = None
    roman_front_matter: bool | None = None
    show_running_head: bool | None = None
    header_text: str | None = Field(default=None, max_length=300)
    footer_text: str | None = Field(default=None, max_length=300)
    number_headings: bool | None = None
    number_figures: bool | None = None
    number_tables: bool | None = None
    number_equations: bool | None = None
    embed_remote_images: bool | None = None
    bibliography_heading: str | None = Field(default=None, max_length=300)
    toc_heading: str | None = Field(default=None, max_length=300)
    list_of_figures_heading: str | None = Field(default=None, max_length=300)
    list_of_tables_heading: str | None = Field(default=None, max_length=300)

    def to_payload(self) -> dict[str, Any]:
        """Only the fields the author actually set, so the server defaults still apply."""
        return {key: value for key, value in self.model_dump(exclude_unset=True).items()}


class ExportPreviewRequest(BaseModel):
    """A dry run: what the export would contain, without generating a file."""

    format: ExportFormat = "pdf"
    options: ExportOptionsRequest = Field(default_factory=ExportOptionsRequest)


class ExportPreviewResponse(BaseModel):
    format: ExportFormat
    style: str
    style_label: str
    project_title: str
    section_count: int
    section_titles: list[str]
    figure_count: int
    table_count: int
    citation_count: int
    bibliography_entries: int
    uncited_count: int
    orphan_count: int
    annex_count: int
    warnings: list[str]
    has_cover: bool
    has_toc: bool


class ExportRecordResponse(BaseModel):
    id: UUID
    project_id: UUID
    format: ExportFormat
    file_name: str
    size_bytes: int
    style: str | None
    style_label: str | None
    section_count: int
    figure_count: int
    table_count: int
    citation_count: int
    uncited_count: int
    orphan_count: int
    warnings: list[str]
    duration_ms: int | None
    created_at: datetime


class ExportListResponse(BaseModel):
    items: list[ExportRecordResponse]
    total: int


class ExportFormatInfo(BaseModel):
    format: ExportFormat
    label: str
    extension: str
    media_type: str


class ExportCatalogueResponse(BaseModel):
    """Everything the export dialog needs, so the frontend hard-codes nothing."""

    formats: list[ExportFormatInfo]
    page_sizes: list[str]
    fonts: list[str]
    defaults: dict[str, Any]


__all__ = [
    "EXPORT_FORMATS",
    "PAGE_SIZES",
    "PDF_FONTS",
    "ExportCatalogueResponse",
    "ExportFormat",
    "ExportFormatInfo",
    "ExportListResponse",
    "ExportOptionsRequest",
    "ExportPreviewRequest",
    "ExportPreviewResponse",
    "ExportRecordResponse",
]
