"""Observability HTTP API: metrics for scraping, security events for an operator.

The metrics endpoint is deliberately cheap and unauthenticated-but-opaque: it exposes only
counters, never a route parameter that would identify a project, and the payload states that
it is per process. It is not a place to read user data.

The security events endpoint requires an administrator, because an event log contains the
fingerprints of who did what.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth
from app.core.config import get_settings
from app.db.session import get_session
from app.models.security import SecurityEvent
from app.observability.metrics import REGISTRY
from app.security.admin import require_admin

router = APIRouter(prefix="/api/observability", tags=["observability"])
settings = get_settings()


@router.get("/metrics")
async def metrics_endpoint() -> dict[str, Any]:
    """Counters and latencies for this process, ready to be scraped."""
    return REGISTRY.snapshot(settings.version)


@router.get("/health/details")
async def health_details_endpoint() -> dict[str, Any]:
    """What the readiness probe checks, exposed for an operator.

    It names the dependencies and their state, and nothing else: no host, no credential, no
    version of anything that is not already public in the build.
    """
    from app.api.health import check_database, check_redis

    database_ok = await check_database()
    redis_ok = await check_redis()
    return {
        "status": "ok" if database_ok and redis_ok else "degraded",
        "checked_at": datetime.now(UTC).isoformat(),
        "dependencies": {
            "postgres": "ok" if database_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
        "version": settings.version,
        "environment": settings.app_env,
    }


@router.get("/security-events")
async def security_events_endpoint(
    kind: str | None = Query(default=None, max_length=48),
    user_id: UUID | None = Query(default=None),
    since_hours: int = Query(default=168, ge=1, le=8760),
    limit: int = Query(default=100, ge=1, le=500),
    auth: CurrentAuth = Depends(get_current_auth),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Read the security event log. Administrator only."""
    require_admin(auth.user)
    since = datetime.now(UTC).timestamp() - since_hours * 3600
    conditions = [
        SecurityEvent.created_at
        >= datetime.fromtimestamp(since, tz=UTC)
    ]
    if kind:
        conditions.append(SecurityEvent.kind == kind)
    if user_id:
        conditions.append(SecurityEvent.user_id == user_id)
    total = int(
        (
            await db.execute(select(func.count(SecurityEvent.id)).where(*conditions))
        ).scalar_one()
    )
    rows = (
        (
            await db.execute(
                select(SecurityEvent)
                .where(*conditions)
                .order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "user_id": str(row.user_id) if row.user_id else None,
                "project_id": str(row.project_id) if row.project_id else None,
                "resource": row.resource,
                "outcome": row.outcome,
                "detail": row.detail,
                "path": row.path,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": total,
        "since_hours": since_hours,
    }


@router.post("/metrics/reset")
async def reset_metrics_endpoint(
    auth: CurrentAuth = Depends(get_current_auth),
) -> dict[str, Any]:
    """Clear the in-process counters. Administrator only, and useful after a diagnosis."""
    require_admin(auth.user)
    REGISTRY.reset()
    return {"status": "reset"}


__all__ = ["router"]
