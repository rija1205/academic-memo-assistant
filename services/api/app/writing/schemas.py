"""Pydantic contracts of the assisted writing API.

Every response describes a *proposal*. There is no endpoint that applies a proposal to the
thesis: applying it is a separate, explicit action performed by the editor through the
existing section-save route, which keeps its version control and revision history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.writing.actions import WritingAction

GenerationStatus = Literal["completed", "insufficient_sources", "failed", "discarded"]


class WritingCitationResponse(BaseModel):
    position: int
    citation_id: str
    chunk_id: UUID | None = None
    source_id: UUID | None = None
    source_file_id: UUID | None = None
    provenance_id: UUID | None = None
    page: int
    quote: str
    rag_score: float
    source_title: str | None = None
    original_filename: str
    deep_link: str = ""


class WritingRequest(BaseModel):
    """One writing request coming from the editor."""

    action: WritingAction
    instruction: str = Field(default="", max_length=1000)
    selection: str = Field(default="", max_length=20000)
    section_text: str = Field(default="", max_length=60000)
    previous_text: str = Field(default="", max_length=4000)
    section_id: UUID | None = None
    target_language: str | None = Field(default=None, max_length=32)

    @field_validator("instruction", "selection", "section_text", "previous_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class WritingResponse(BaseModel):
    """A proposal. The thesis is never modified by this call."""

    generation_id: UUID
    action: WritingAction
    status: GenerationStatus
    proposed_text: str
    user_message: str
    citations: list[WritingCitationResponse] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)
    grounding_note: str | None = None
    used_sources: bool = False
    chunks_retrieved: int = 0
    reranked: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    cost_is_estimate: bool = True
    rag_duration_ms: int = 0
    llm_duration_ms: int = 0
    error_category: str | None = None
    created_at: datetime


class WritingGenerationSummary(BaseModel):
    id: UUID
    project_id: UUID
    section_id: UUID | None = None
    action: WritingAction
    status: GenerationStatus
    instruction: str
    selection_excerpt: str
    proposed_text: str
    llm_provider: str | None = None
    llm_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    cost_is_estimate: bool = True
    chunks_retrieved: int = 0
    used_sources: bool = False
    grounding_note: str | None = None
    error_category: str | None = None
    applied_at: datetime | None = None
    created_at: datetime
    citations: list[WritingCitationResponse] = Field(default_factory=list)


class WritingGenerationListResponse(BaseModel):
    items: list[WritingGenerationSummary]
    total: int


class WritingActionResponse(BaseModel):
    action: str
    label: str
    description: str
    uses_sources: bool
    needs_selection: bool
    needs_full_section: bool


class WritingCatalogResponse(BaseModel):
    actions: list[WritingActionResponse]
    top_k: int
    max_selection_chars: int
    max_section_chars: int


__all__ = [
    "GenerationStatus",
    "WritingActionResponse",
    "WritingCatalogResponse",
    "WritingCitationResponse",
    "WritingGenerationListResponse",
    "WritingGenerationSummary",
    "WritingRequest",
    "WritingResponse",
]
