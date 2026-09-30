"""Pydantic contracts of the audit API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SeverityName = Literal["blocker", "warning", "info"]
ReadinessLevel = Literal["aucun_bloquant", "corrections_requises", "reprise_necessaire"]


class AuditFindingResponse(BaseModel):
    code: str
    severity: SeverityName
    severity_label: str
    title: str
    detail: str
    location_kind: str | None = None
    location_ref: str | None = None
    location_label: str | None = None
    remedy: str | None = None
    count: int = 1
    meta: dict[str, Any] = Field(default_factory=dict)


class AuditCheckResponse(BaseModel):
    code: str
    finding_count: int
    #: Set when the check could not conclude; the report then says so instead of implying a pass.
    skipped_reason: str | None = None


class AuditReadinessResponse(BaseModel):
    level: ReadinessLevel
    label: str
    detail: str


class AuditObservationResponse(BaseModel):
    code: str
    label: str
    detail: str


class DefenceChecklistItem(BaseModel):
    priority: int
    category: str
    question: str
    evidence: str | None = None


class SectionStatResponse(BaseModel):
    section_id: str
    title: str
    level: int
    word_count: int
    citation_count: int
    figure_count: int
    table_count: int
    status: str
    citation_density: float | None = None
    read_minutes: float = 0.0


class ThesisStatsResponse(BaseModel):
    project_id: str
    title: str
    section_count: int
    chapter_count: int
    subsection_count: int
    empty_section_count: int
    completed_section_count: int
    word_count: int
    character_count: int
    read_minutes: float
    longest_section: str | None = None
    longest_section_words: int = 0
    average_section_words: int = 0
    citation_count: int
    distinct_cited_references: int
    orphan_citation_count: int
    pending_citation_count: int
    narrative_citation_count: int
    reference_count: int
    uncited_reference_count: int
    references_with_doi: int
    references_with_url: int
    reference_type_counts: dict[str, int]
    reference_year_span: list[int] | None = None
    most_cited_references: list[dict[str, Any]]
    citation_density: float | None = None
    bibliography_style: str
    dangling_citation_references: int = 0
    source_count: int
    indexed_source_count: int
    source_page_count: int
    source_block_count: int
    figure_count: int
    table_count: int
    equation_count: int
    sections: list[SectionStatResponse]


class AuditSummaryResponse(BaseModel):
    blockers: int
    warnings: int
    info: int
    checks_run: int
    checks_inconclusive: int
    labels: dict[str, str]


class AuditReportResponse(BaseModel):
    project_id: str
    project_title: str
    generated_at: str
    readiness: AuditReadinessResponse
    summary: AuditSummaryResponse
    findings: list[AuditFindingResponse]
    findings_by_code: dict[str, int]
    checks: list[AuditCheckResponse]
    statistics: ThesisStatsResponse
    observations: list[AuditObservationResponse]
    defence_checklist: list[DefenceChecklistItem]
    disclaimer: str


class AuditRunRequest(BaseModel):
    """Run an audit and, optionally, keep the trace.

    ``store_trace`` is false by default: consulting an audit is a read and should not grow the
    table. Storing is explicit, which is also what a weekly progress check does.
    """

    store_trace: bool = False


class AuditRunResponse(BaseModel):
    report: AuditReportResponse
    trace_id: UUID | None = None
    duration_ms: int


class AuditTraceResponse(BaseModel):
    id: UUID
    project_id: UUID
    readiness: ReadinessLevel
    blocker_count: int
    warning_count: int
    info_count: int
    checks_run: int
    checks_inconclusive: int
    word_count: int
    citation_count: int
    reference_count: int
    findings: list[dict[str, Any]]
    duration_ms: int | None
    created_at: datetime


class AuditTraceListResponse(BaseModel):
    items: list[AuditTraceResponse]
    total: int
    #: Change in the blocker count between the first and the most recent trace, when both
    #: exist. ``None`` means it cannot be computed, not that it is zero.
    blocker_trend: int | None = None


__all__ = [
    "AuditCheckResponse",
    "AuditFindingResponse",
    "AuditObservationResponse",
    "AuditReadinessResponse",
    "AuditReportResponse",
    "AuditRunRequest",
    "AuditRunResponse",
    "AuditSummaryResponse",
    "AuditTraceListResponse",
    "AuditTraceResponse",
    "DefenceChecklistItem",
    "ReadinessLevel",
    "SectionStatResponse",
    "SeverityName",
    "ThesisStatsResponse",
]
