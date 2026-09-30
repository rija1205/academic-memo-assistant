"""Platform administration HTTP API.

Every route requires an administrator. The check is applied once, as a dependency, so no route
can forget it, and the project-level permission model is untouched: an administrator manages
accounts, and manages *no* memoir content.

The routes are under ``/api/admin``, not ``/api/projects/{id}``, because they are not scoped
to a project. That is also why they are excluded from the project isolation helpers on
purpose: there is no project to isolate from.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.db.session import get_session
from app.models.security import AdminAuditEvent
from app.security.admin import (
    get_user_view,
    list_users,
    platform_stats,
    require_admin,
    set_admin,
    set_suspended,
)
from app.security.guards import SecurityEventKind, current_event_log

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_platform_admin(
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> CurrentAuth:
    """The single gate in front of every administrative route."""
    require_admin(current_auth.user)
    return current_auth


@router.get("/users")
async def list_users_endpoint(
    query: str | None = Query(default=None, max_length=200),
    only_suspended: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Search accounts. Metadata only: an administrator cannot read a memoir here."""
    users, total = await list_users(
        db, query=query, only_suspended=only_suspended, limit=limit, offset=offset
    )
    return {
        "items": [user.as_dict() for user in users],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
async def stats_endpoint(
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Aggregate platform numbers. No content, only counts."""
    return await platform_stats(db)


@router.get("/users/{user_id}")
async def get_user_endpoint(
    user_id: UUID,
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return (await get_user_view(db, user_id)).as_dict()


@router.post("/users/{user_id}/suspension")
async def set_suspension_endpoint(
    user_id: UUID,
    request: Request,
    suspended: bool = Query(..., description="true pour suspendre, false pour réintégrer"),
    reason: str | None = Query(default=None, max_length=400),
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> dict[str, Any]:
    """Suspend or reinstate an account, and record who decided and why."""
    view = await set_suspended(
        db, user_id=user_id, suspended=suspended, reason=reason, actor=auth.user
    )
    db.add(
        AdminAuditEvent(
            actor_id=auth.user.id,
            target_user_id=user_id,
            action="suspend" if suspended else "reinstate",
            target=view.email,
            reason=(reason or "").strip() or None,
        )
    )
    await db.commit()
    # The security event log lives on the request, so it is written once with everything else
    # the request recorded rather than in a separate path.
    current_event_log(request).record(
        SecurityEventKind.ACCOUNT_SUSPENDED,
        actor_id=str(auth.user.id),
        resource=view.email,
        outcome="success",
        detail=reason,
    )
    return view.as_dict()


@router.post("/users/{user_id}/administrator")
async def set_administrator_endpoint(
    user_id: UUID,
    is_admin: bool = Query(..., description="true pour accorder, false pour retirer"),
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> dict[str, Any]:
    """Grant or revoke the administrator flag, and record it."""
    view = await set_admin(
        db, user_id=user_id, is_admin=is_admin, actor=auth.user
    )
    db.add(
        AdminAuditEvent(
            actor_id=auth.user.id,
            target_user_id=user_id,
            action="grant_admin" if is_admin else "revoke_admin",
            target=view.email,
        )
    )
    await db.commit()
    return view.as_dict()


@router.get("/admin-actions")
async def list_admin_actions_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    auth: CurrentAuth = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """What administrators have done, most recent first."""
    from sqlalchemy import select

    rows = (
        (
            await db.execute(
                select(AdminAuditEvent)
                .order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc())
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
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "target_user_id": str(row.target_user_id) if row.target_user_id else None,
                "action": row.action,
                "target": row.target,
                "reason": row.reason,
                "outcome": row.outcome,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
