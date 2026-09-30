"""Pydantic contracts of the RAG search API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.rag.provenance import RagProvenance, RagSourceSummary
from app.rag.settings import (
    FUSION_NORMALIZED,
    FUSION_RRF,
    STRATEGY_HYBRID,
    STRATEGY_LEXICAL,
    STRATEGY_SEMANTIC,
)

Strategy = Literal["semantic", "lexical", "hybrid"]
FusionMethod = Literal["rrf", "normalized"]
PublicationTypeFilter = Literal[
    "article", "book", "book_chapter", "thesis", "memo", "report", "conference", "website", "other"
]


class RagSearchFilters(BaseModel):
    """Optional academic filters. Every filter stays inside the current project."""

    source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    publication_types: list[PublicationTypeFilter] = Field(default_factory=list, max_length=9)
    year_from: int | None = Field(default=None, ge=1000, le=3000)
    year_to: int | None = Field(default=None, ge=1000, le=3000)
    authors: list[str] = Field(default_factory=list, max_length=20)
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    folder_ids: list[UUID] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("authors", "tags")
    @classmethod
    def _strip_values(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]

    @field_validator("publication_types")
    @classmethod
    def _dedupe_types(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=200)
    strategy: Strategy | None = None
    fusion_method: FusionMethod | None = None
    filters: RagSearchFilters = Field(default_factory=RagSearchFilters)

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("La requête doit contenir au moins deux caractères.")
        return stripped


class RagSearchResult(BaseModel):
    chunk_id: UUID
    text: str
    score: float
    vector_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None
    vector_rank: int | None = None
    lexical_rank: int | None = None
    token_count: int
    source: RagSourceSummary
    page: int
    provenance: RagProvenance
    citation_marker: str


class RagSearchResponse(BaseModel):
    query: str
    strategy: Strategy
    fusion_method: FusionMethod | None = None
    reranker: str = "none"
    top_k: int
    total_candidates: int
    duration_ms: int
    vector_hits: int
    lexical_hits: int
    results: list[RagSearchResult] = Field(default_factory=list)


class RagDocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_id: UUID
    source_title: str | None = None
    original_filename: str
    status: str
    index_signature: str
    embedding_provider: str
    embedding_model: str
    embedding_version: str
    chunking_version: str
    embedding_dimension: int
    chunk_count: int
    token_count: int
    estimated_cost_usd: float
    page_count: int | None = None
    error_message: str | None = None
    attempts: int
    indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    needs_reindex: bool


class RagDocumentListResponse(BaseModel):
    items: list[RagDocumentResponse]
    total: int


class RagStatsResponse(BaseModel):
    documents_total: int
    documents_indexed: int
    documents_pending: int
    chunks_total: int
    tokens_total: int
    estimated_cost_usd: float
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    embedding_version: str
    chunking_version: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    search_strategy: Strategy
    fusion_method: FusionMethod
    reranker: str


class RagQueryHistoryResponse(BaseModel):
    id: UUID
    query: str
    strategy: str
    fusion_method: str | None = None
    top_k: int
    result_count: int
    semantic_hits: int
    lexical_hits: int
    duration_ms: int
    created_at: datetime


class RagQueryHistoryListResponse(BaseModel):
    items: list[RagQueryHistoryResponse]


class RagIndexActionResponse(BaseModel):
    message: str
    document: RagDocumentResponse | None = None
    queued: bool = False


__all__ = [
    "FUSION_NORMALIZED",
    "FUSION_RRF",
    "RagDocumentListResponse",
    "RagDocumentResponse",
    "RagIndexActionResponse",
    "RagQueryHistoryListResponse",
    "RagQueryHistoryResponse",
    "RagSearchFilters",
    "RagSearchRequest",
    "RagSearchResponse",
    "RagSearchResult",
    "RagStatsResponse",
    "STRATEGY_HYBRID",
    "STRATEGY_LEXICAL",
    "STRATEGY_SEMANTIC",
]
