"""Academic audit HTTP API.

A ``reader`` may read the audit: seeing what is missing is not a privilege. An ``editor`` may
run it and keep a trace, and an ``owner`` may delete a trace, because a trace is a record
rather than content.

The audit **never writes to the memoir**. No endpoint here can modify a section, a citation or
a reference; the only thing an audit produces is a report and, on request, a stored trace.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.schemas import (
    AuditReportResponse,
    AuditRunRequest,
    AuditRunResponse,
    AuditTraceListResponse,
    AuditTraceResponse,
)
from app.audit.service import (
    build_audit_report,
    collect_audit_data,
    run_checks,
)
from app.audit.statistics import compute_stats
from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.db.session import get_session
from app.models.audit import AcademicAudit
from app.models.project import Project
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_owner,
    require_project_reader,
)

router = APIRouter(prefix="/api/projects/{project_id}/audit", tags=["audit"])

#: Bounded so a request cannot ask for an unbounded trace list.
MAX_TRACES = 100


async def _project_or_404(db: AsyncSession, project_id: UUID) -> Project:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Mémoire introuvable.")
    return project


def _current_academic_year() -> str:
    """The academic year the platform considers current, used to spot a stale memoir.

    Computed, not stored, so it never has to be kept in sync by hand.
    """
    now = datetime.now(UTC)
    start = now.year if now.month >= 9 else now.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


@router.post("/run", response_model=AuditRunResponse)
async def run_audit_endpoint(
    project_id: UUID,
    payload: AuditRunRequest | None = None,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> AuditRunResponse:
    """Run the full academic audit and return the report.

    The audit is deterministic: the same data always produces the same report. It writes
    nothing to the memoir.
    """
    await _project_or_404(db, project_id)
    started = time.perf_counter()
    data = await collect_audit_data(
        db,
        project_id=project_id,
        current_academic_year=_current_academic_year(),
    )
    outcomes = run_checks(data)
    stats = compute_stats(data)
    report = build_audit_report(data, outcomes, stats)
    duration = int((time.perf_counter() - started) * 1000)

    trace_id: UUID | None = None
    if payload is not None and payload.store_trace:
        trace = AcademicAudit(
            project_id=project_id,
            user_id=current_auth.user.id,
            readiness=report["readiness"]["level"],
            blocker_count=report["summary"]["blockers"],
            warning_count=report["summary"]["warnings"],
            info_count=report["summary"]["info"],
            checks_run=report["summary"]["checks_run"],
            checks_inconclusive=report["summary"]["checks_inconclusive"],
            word_count=report["statistics"]["word_count"],
            citation_count=report["statistics"]["citation_count"],
            reference_count=report["statistics"]["reference_count"],
            # Only the findings, never the memoir's text.
            findings=report["findings"],
            duration_ms=duration,
        )
        db.add(trace)
        await db.commit()
        await db.refresh(trace)
        trace_id = trace.id

    return AuditRunResponse(
        report=AuditReportResponse(**report), trace_id=trace_id, duration_ms=duration
    )


@router.get("", response_model=AuditReportResponse)
async def audit_endpoint(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> AuditReportResponse:
    """Read the audit without running the trace endpoint.

    A reader may see the report: it contains no content the reader could not already read, and
    hiding it would only make a student discover the problem at the worst moment.
    """
    await _project_or_404(db, project_id)
    data = await collect_audit_data(
        db, project_id=project_id, current_academic_year=_current_academic_year()
    )
    outcomes = run_checks(data)
    stats = compute_stats(data)
    return AuditReportResponse(**build_audit_report(data, outcomes, stats))


@router.get("/traces", response_model=AuditTraceListResponse)
async def list_traces_endpoint(
    project_id: UUID,
    limit: int = Query(default=20, ge=1, le=MAX_TRACES),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> AuditTraceListResponse:
    """The audit history of this project, most recent first."""
    await _project_or_404(db, project_id)
    total = int(
        (
            await db.execute(
                select(func.count(AcademicAudit.id)).where(
                    AcademicAudit.project_id == project_id
                )
            )
        ).scalar_one()
    )
    rows = (
        (
            await db.execute(
                select(AcademicAudit)
                .where(AcademicAudit.project_id == project_id)
                .order_by(
                    AcademicAudit.created_at.desc(), AcademicAudit.id.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    # The trend is the blocker count of the oldest trace minus that of the most recent one.
    # ``None`` when there is not enough history to say anything.
    extremes = (
        (
            await db.execute(
                select(AcademicAudit.blocker_count)
                .where(AcademicAudit.project_id == project_id)
                .order_by(AcademicAudit.created_at.asc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    trend: int | None = None
    if extremes is not None and len(rows) > 1:
        trend = int(extremes) - int(rows[0].blocker_count)
    return AuditTraceListResponse(
        items=[
            AuditTraceResponse(
                id=row.id,
                project_id=row.project_id,
                readiness=row.readiness,  # type: ignore[arg-type]
                blocker_count=row.blocker_count,
                warning_count=row.warning_count,
                info_count=row.info_count,
                checks_run=row.checks_run,
                checks_inconclusive=row.checks_inconclusive,
                word_count=row.word_count,
                citation_count=row.citation_count,
                reference_count=row.reference_count,
                findings=list(row.findings or []),
                duration_ms=row.duration_ms,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        blocker_trend=trend,
    )


@router.delete("/traces/{trace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trace_endpoint(
    project_id: UUID,
    trace_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    """Delete one audit trace. Scoped to the project, so a foreign id answers 404."""
    await _project_or_404(db, project_id)
    trace = (
        await db.execute(
            select(AcademicAudit).where(
                AcademicAudit.id == trace_id,
                AcademicAudit.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace d'audit introuvable.")
    await db.delete(trace)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
