"""Structured provenance.

Every retrieved passage resolves to the full chain required by an academic citation:

``project -> source -> source file -> page -> block -> provenance id -> chunk``

The object is returned by the search API so that a later writing assistant can cite a passage
without re-querying the database, and so the user can always open the exact page.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.rag.search.retrieval import ScoredChunk


class RagProvenance(BaseModel):
    """Complete, verifiable origin of a retrieved passage."""

    project_id: UUID
    chunk_id: UUID
    rag_document_id: UUID
    source_id: UUID
    source_file_id: UUID | None = None
    original_filename: str
    source_title: str | None = None
    source_authors: list[str] = Field(default_factory=list)
    source_year: int | None = None
    page_number: int
    block_start: int
    block_end: int
    chunk_index: int
    provenance_id: UUID
    character_start: int | None = None
    character_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    block_types: list[str] = Field(default_factory=list)
    sentence_split: bool = False
    source_url: str = ""

    def as_citation_marker(self) -> str:
        """Short human-readable reference, e.g. ``Auteur (2024), p. 12``."""
        author = self.source_authors[0] if self.source_authors else None
        year = f" ({self.source_year})" if self.source_year else ""
        page = f", p. {self.page_number}" if self.page_number else ""
        title = f"« {self.source_title} »" if self.source_title else self.original_filename
        return f"{author}{year}{page}, {title}" if author else f"{title}{year}{page}"


class RagSourceSummary(BaseModel):
    """Academic identity returned with each result."""

    id: UUID
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    publication_type: str = "other"
    journal: str | None = None
    doi: str | None = None
    original_filename: str
    page_count: int | None = None
    tags: list[str] = Field(default_factory=list)
    folder_id: UUID | None = None
    file_id: UUID | None = None


class RagSearchResult(BaseModel):
    """One retrieved passage with its score breakdown and provenance."""

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
    strategy: str
    fusion_method: str | None = None
    reranker: str
    top_k: int
    total_candidates: int
    duration_ms: int
    vector_hits: int
    lexical_hits: int
    results: list[RagSearchResult] = Field(default_factory=list)


def build_provenance(chunk: ScoredChunk, *, project_id: UUID) -> RagProvenance:
    """Build the structured provenance of a retrieved chunk."""
    metadata: dict[str, Any] = dict(chunk.metadata or {})
    heading_path = metadata.get("heading_path") or []
    block_types = metadata.get("block_types") or []
    return RagProvenance(
        project_id=project_id,
        chunk_id=chunk.chunk_id,
        rag_document_id=chunk.rag_document_id,
        source_id=chunk.source.id,
        source_file_id=chunk.source.file_id,
        original_filename=chunk.source.original_filename,
        source_title=chunk.source.title,
        source_authors=list(chunk.source.authors),
        source_year=chunk.source.publication_year,
        page_number=chunk.page_number,
        block_start=chunk.block_start,
        block_end=chunk.block_end,
        chunk_index=chunk.chunk_index,
        provenance_id=chunk.provenance_id,
        character_start=metadata.get("character_start"),
        character_end=metadata.get("character_end"),
        heading_path=[str(value) for value in heading_path],
        block_types=[str(value) for value in block_types],
        sentence_split=bool(metadata.get("sentence_split", False)),
        source_url=(
            f"/api/projects/{project_id}/sources/{chunk.source.id}"
            f"/preview?page={chunk.page_number}"
        ),
    )


def build_source_summary(chunk: ScoredChunk) -> RagSourceSummary:
    source = chunk.source
    return RagSourceSummary(
        id=source.id,
        title=source.title,
        authors=list(source.authors),
        year=source.publication_year,
        publication_type=source.publication_type,
        journal=source.journal,
        doi=source.doi,
        original_filename=source.original_filename,
        page_count=source.page_count,
        tags=list(source.tags),
        folder_id=source.folder_id,
        file_id=source.file_id,
    )
