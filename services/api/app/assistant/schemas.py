"""Pydantic contracts of the assistant API.

The API key is never part of any schema in this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

AnswerStatus = Literal["completed", "insufficient_sources", "failed"]
UserRole = Literal["user", "assistant", "system"]


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)


class ConversationSummaryResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    total: int


class CitationResponse(BaseModel):
    """A citation built from a retrieved passage, never from model output."""

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
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    deep_link: str = ""


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: UserRole
    content: str
    status: str
    sequence: int
    llm_provider: str | None = None
    llm_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    cost_is_estimate: bool = True
    rag_duration_ms: int = 0
    llm_duration_ms: int = 0
    chunks_retrieved: int = 0
    error_category: str | None = None
    grounding_note: str | None = None
    created_at: datetime
    citations: list[CitationResponse] = Field(default_factory=list)


class ConversationDetailResponse(ConversationSummaryResponse):
    summary: str | None = None
    messages: list[MessageResponse] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=2)
    conversation_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("La question doit contenir au moins deux caractères.")
        return cleaned


class AskResponse(BaseModel):
    """Answer to a question.

    ``answer`` is ``None`` and ``status`` is ``insufficient_sources`` when the retrieval stage
    found nothing usable. In that case no language model is called at all.
    """

    status: AnswerStatus
    message_id: UUID
    conversation_id: UUID
    question: str
    answer: str | None = None
    user_message: str
    citations: list[CitationResponse] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)
    grounding_note: str | None = None
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
    created_at: datetime


class AssistantUsageResponse(BaseModel):
    questions_used_today: int
    daily_tokens_used: int
    daily_tokens_remaining: int
    max_questions_per_minute: int
    max_daily_tokens: int
    rate_limit_enabled: bool


class AssistantConfigResponse(BaseModel):
    provider: str
    model: str
    temperature: float
    max_output_tokens: int
    max_input_tokens: int
    max_history_messages: int
    top_k: int
    min_context_score: float
    rate_limit_enabled: bool


class ConversationDeleteResponse(BaseModel):
    message: str
    conversation_id: UUID


__all__ = [
    "AnswerStatus",
    "AskRequest",
    "AskResponse",
    "AssistantConfigResponse",
    "AssistantUsageResponse",
    "CitationResponse",
    "ConversationCreateRequest",
    "ConversationDeleteResponse",
    "ConversationDetailResponse",
    "ConversationListResponse",
    "ConversationSummaryResponse",
    "MessageResponse",
    "UserRole",
]
