"""Pydantic contracts of the citation API."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

LocatorType = Literal[
    "page", "pages", "chapter", "figure", "table", "section", "other"
]
CitationMode = Literal["parenthetical", "narrative"]

MAX_PREFIX = 255
MAX_SUFFIX = 255
MAX_LOCATOR = 120
MAX_REFERENCES_PER_CITATION = 20
MAX_TITLE = 1000


class CitationItemInput(BaseModel):
    """One reference inside a citation."""

    reference_id: UUID
    locator_type: LocatorType | None = None
    locator_value: str | None = Field(default=None, max_length=MAX_LOCATOR)
    prefix: str | None = Field(default=None, max_length=MAX_PREFIX)
    suffix: str | None = Field(default=None, max_length=MAX_SUFFIX)

    @field_validator("locator_value", "prefix", "suffix")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CitationCreateRequest(BaseModel):
    """Create a citation, or update the one that already owns the node."""

    section_id: UUID
    node_id: str = Field(min_length=1, max_length=120)
    items: list[CitationItemInput] = Field(min_length=1, max_length=MAX_REFERENCES_PER_CITATION)
    prefix: str | None = Field(default=None, max_length=MAX_PREFIX)
    suffix: str | None = Field(default=None, max_length=MAX_SUFFIX)
    locator_type: LocatorType | None = None
    locator_value: str | None = Field(default=None, max_length=MAX_LOCATOR)
    mode: CitationMode = "parenthetical"
    position_in_section: int = Field(default=0, ge=0, le=100000)

    @field_validator("prefix", "suffix", "locator_value", "node_id")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CitationUpdateRequest(BaseModel):
    """Partial update. Only the fields present in the request are modified."""

    items: list[CitationItemInput] | None = Field(
        default=None, min_length=1, max_length=MAX_REFERENCES_PER_CITATION
    )
    prefix: str | None = Field(default=None, max_length=MAX_PREFIX)
    suffix: str | None = Field(default=None, max_length=MAX_SUFFIX)
    locator_type: LocatorType | None = None
    locator_value: str | None = Field(default=None, max_length=MAX_LOCATOR)
    mode: CitationMode | None = None
    position_in_section: int | None = Field(default=None, ge=0, le=100000)
    #: Detach an item instead of deleting the whole citation, used by the repair screen.
    remove_reference_id: UUID | None = None


class CitationItemResponse(BaseModel):
    reference_id: UUID
    citation_key: str | None
    title: str | None
    publication_year: int | None
    author_labels: list[str]
    position: int
    locator_type: LocatorType | None
    locator_value: str | None
    prefix: str | None
    suffix: str | None
    #: False when the reference was deleted: the citation is then invalid.
    is_available: bool
    number: int | None = None


class CitationResponse(BaseModel):
    id: UUID
    project_id: UUID
    section_id: UUID
    node_id: str
    citation_key: str
    prefix: str | None
    suffix: str | None
    locator_type: LocatorType | None
    locator_value: str | None
    mode: CitationMode
    position_in_section: int
    items: list[CitationItemResponse]
    #: The text exactly as the current style and the current references produce it.
    rendered_text: str
    #: What could not be honoured: a missing author, a missing year, a deleted reference.
    warnings: list[str]
    is_orphaned: bool
    is_complete: bool
    #: True when the reference was renamed or re-dated: the display is derived, not stored.
    is_stale_snapshot: bool
    snapshot_text: str | None
    created_at: str
    updated_at: str


class CitationListResponse(BaseModel):
    items: list[CitationResponse]
    total: int


class RenderedCitationResponse(BaseModel):
    """One citation as the editor must display it."""

    node_id: str
    citation_id: str | None
    text: str
    is_orphaned: bool
    warnings: list[str]
    reference_ids: list[str]


class SectionRenderResponse(BaseModel):
    section_id: UUID
    style: str
    style_label: str
    citations: list[RenderedCitationResponse]
    orphaned: list[str]


class RenderedBibliographyEntryResponse(BaseModel):
    reference_id: UUID
    number: int | None
    text: str
    warnings: list[str]
    citation_keys: list[str]
    is_complete: bool


class RenderedBibliographyResponse(BaseModel):
    style: str
    style_label: str
    entries: list[RenderedBibliographyEntryResponse]
    cited_count: int
    uncited_count: int
    #: References present in the library but never cited: they stay in the library and are
    #: simply absent from the final bibliography.
    uncited: list[UncitedReferenceResponse]
    #: Citations whose reference disappeared, with the frozen text that used to be shown.
    orphaned_citations: list[OrphanedCitationResponse]
    incomplete_count: int
    is_truncated: bool


class UncitedReferenceResponse(BaseModel):
    reference_id: UUID
    citation_key: str
    title: str | None
    publication_year: int | None
    reference_type: str


class OrphanedCitationResponse(BaseModel):
    citation_id: UUID
    node_id: str
    section_id: UUID
    missing_reference_ids: list[str]
    snapshot_text: str | None
    snapshot_style: str | None
    message: str


class DocumentCitationCheckResponse(BaseModel):
    """Result of comparing the Tiptap document with the citation rows."""

    section_id: UUID
    style: str
    citations: list[RenderedCitationResponse]
    #: Nodes present in the document that have no row yet.
    unregistered_node_ids: list[str]
    #: Rows that no longer appear in the document.
    stale_citation_ids: list[str]
    orphaned_node_ids: list[str]
    synced: int


class StyleCatalogueEntry(BaseModel):
    name: str
    label: str
    uses_numbers: bool
    date_missing: str


class PreviewRequest(BaseModel):
    """Render a citation that is not stored yet, for the picker preview."""

    style: str | None = None
    items: list[CitationItemInput] = Field(
        min_length=1, max_length=MAX_REFERENCES_PER_CITATION
    )
    prefix: str | None = Field(default=None, max_length=MAX_PREFIX)
    suffix: str | None = Field(default=None, max_length=MAX_SUFFIX)
    mode: CitationMode = "parenthetical"


class PreviewResponse(BaseModel):
    style: str
    style_label: str
    citation: str
    bibliography_entry: str
    warnings: list[str]
    #: True when the preview really came from the style engine used for rendering.
    uses_style_engine: bool = True


RenderedBibliographyResponse.model_rebuild()


__all__ = [
    "MAX_LOCATOR",
    "MAX_PREFIX",
    "MAX_REFERENCES_PER_CITATION",
    "MAX_SUFFIX",
    "MAX_TITLE",
    "CitationCreateRequest",
    "CitationItemInput",
    "CitationItemResponse",
    "CitationListResponse",
    "CitationResponse",
    "CitationUpdateRequest",
    "DocumentCitationCheckResponse",
    "OrphanedCitationResponse",
    "PreviewRequest",
    "PreviewResponse",
    "RenderedBibliographyEntryResponse",
    "RenderedBibliographyResponse",
    "RenderedCitationResponse",
    "SectionRenderResponse",
    "StyleCatalogueEntry",
    "UncitedReferenceResponse",
]
