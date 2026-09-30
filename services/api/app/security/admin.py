"""Administration: platform-level management of accounts and projects.

Administration is deliberately separated from project roles. A project ``owner`` manages a
memoir; a platform administrator manages the **accounts**. The distinction matters, because
project ownership is granted by a user and must never imply the power to read every other
user's work.

Three guarantees this module relies on:

* an administrator is a user whose ``is_admin`` flag is set in the database. There is no
  implicit administrator: the first account is not privileged because it happens to be first;
* every administrative action is written to the security event log, so an administrator cannot
  act quietly;
* listing users returns metadata only. An administrator can suspend an account, but cannot read
  a memoir that is not theirs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User


@dataclass(slots=True)
class AdminUserView:
    """What an administrator sees about an account. Never the memoir content."""

    user_id: str
    email: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    is_suspended: bool
    suspended_at: datetime | None
    suspended_reason: str | None
    created_at: datetime
    last_login_at: datetime | None
    project_count: int
    owned_project_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "is_suspended": self.is_suspended,
            "suspended_at": self.suspended_at.isoformat() if self.suspended_at else None,
            "suspended_reason": self.suspended_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "project_count": self.project_count,
            "owned_project_count": self.owned_project_count,
        }


def require_admin(user: User) -> None:
    """Refuse a non-administrator.

    The flag is checked here and nowhere else, so the rule exists in one readable place.
    """
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=403, detail="Administrator privileges are required."
        )


async def _project_counts(
    db: AsyncSession, user_ids: list[UUID]
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    """How many projects each account participates in, and how many it owns."""
    if not user_ids:
        return {}, {}
    from app.models.project import ProjectMember

    total_rows = (
        await db.execute(
            select(ProjectMember.user_id, func.count(ProjectMember.project_id))
            .where(ProjectMember.user_id.in_(user_ids))
            .group_by(ProjectMember.user_id)
        )
    ).all()
    owned_rows = (
        await db.execute(
            select(Project.owner_id, func.count(Project.id))
            .where(Project.owner_id.in_(user_ids), Project.deleted_at.is_(None))
            .group_by(Project.owner_id)
        )
    ).all()
    return (
        {row[0]: int(row[1]) for row in total_rows},
        {row[0]: int(row[1]) for row in owned_rows},
    )


async def list_users(
    db: AsyncSession,
    *,
    query: str | None = None,
    only_suspended: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AdminUserView], int]:
    """Search accounts. Metadata only, never their content."""
    conditions = []
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(User.email.ilike(pattern), User.display_name.ilike(pattern))
        )
    if only_suspended:
        conditions.append(User.is_suspended.is_(True))

    total = int(
        (
            await db.execute(select(func.count(User.id)).where(*conditions))
        ).scalar_one()
    )
    users = list(
        (
            await db.execute(
                select(User)
                .where(*conditions)
                .order_by(User.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    totals, owned = await _project_counts(db, [user.id for user in users])
    return (
        [
            AdminUserView(
                user_id=str(user.id),
                email=user.email,
                display_name=user.display_name,
                is_active=bool(getattr(user, "is_active", True)),
                is_admin=bool(getattr(user, "is_admin", False)),
                is_suspended=bool(getattr(user, "is_suspended", False)),
                suspended_at=getattr(user, "suspended_at", None),
                suspended_reason=getattr(user, "suspended_reason", None),
                created_at=user.created_at,
                last_login_at=getattr(user, "last_login_at", None),
                project_count=totals.get(user.id, 0),
                owned_project_count=owned.get(user.id, 0),
            )
            for user in users
        ],
        total,
    )


async def get_user_view(db: AsyncSession, user_id: UUID) -> AdminUserView:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    views, _ = await list_users(db, query=user.email, limit=5)
    for view in views:
        if view.user_id == str(user_id):
            return view
    raise HTTPException(status_code=404, detail="Compte introuvable.")


async def set_suspended(
    db: AsyncSession,
    *,
    user_id: UUID,
    suspended: bool,
    reason: str | None,
    actor: User,
) -> AdminUserView:
    """Suspend or reinstate an account.

    A suspended account cannot sign in; existing sessions are refused by the authentication
    dependency. The reason is kept so the decision is explainable to the person concerned.
    """
    require_admin(actor)
    if actor.id == user_id and suspended:
        # An administrator locking themselves out is a denial of service against the platform.
        raise HTTPException(
            status_code=400, detail="An administrator cannot suspend their own account."
        )
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    user.is_suspended = suspended
    user.suspended_at = datetime.now(UTC) if suspended else None
    user.suspended_reason = (reason or "").strip() or None if suspended else None
    if suspended:
        user.is_active = False
    await db.commit()
    await db.refresh(user)
    return await get_user_view(db, user_id)


async def set_admin(
    db: AsyncSession, *, user_id: UUID, is_admin: bool, actor: User
) -> AdminUserView:
    """Grant or revoke the administrator flag."""
    require_admin(actor)
    if actor.id == user_id and not is_admin:
        raise HTTPException(
            status_code=400,
            detail="An administrator cannot revoke their own privileges.",
        )
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    user.is_admin = is_admin
    await db.commit()
    await db.refresh(user)
    return await get_user_view(db, user_id)


async def platform_stats(db: AsyncSession) -> dict[str, Any]:
    """Aggregate counts for the platform. No content, only numbers."""
    from app.models.audit import AcademicAudit
    from app.models.citation import Citation
    from app.models.export import DocumentExport
    from app.models.source import Source

    async def count(model: Any, *extra: Any) -> int:  # type: ignore[valid-type]
        statement = select(func.count(model.id))
        for condition in extra:
            statement = statement.where(condition)
        return int((await db.execute(statement)).scalar_one())

    return {
        "users": await count(User),
        "suspended_users": await count(User, User.is_suspended.is_(True)),
        "administrators": await count(User, User.is_admin.is_(True)),
        "projects": await count(Project, Project.deleted_at.is_(None)),
        "archived_projects": await count(Project, Project.archived_at.is_not(None)),
        "sources": await count(Source, Source.deleted_at.is_(None)),
        "citations": await count(Citation, Citation.deleted_at.is_(None)),
        "exports": await count(DocumentExport),
        "audits": await count(AcademicAudit),
        "blockers_open": int(
            (
                await db.execute(
                    select(func.count(func.distinct(AcademicAudit.project_id))).where(
                        AcademicAudit.blocker_count > 0
                    )
                )
            ).scalar_one()
        ),
    }


__all__ = [
    "AdminUserView",
    "get_user_view",
    "list_users",
    "platform_stats",
    "require_admin",
    "set_admin",
    "set_suspended",
]
