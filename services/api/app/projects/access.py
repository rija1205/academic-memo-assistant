from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth
from app.db.session import get_session
from app.models.project import Project, ProjectMember


class ProjectRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    READER = "reader"


ROLE_RANK: dict[ProjectRole, int] = {
    ProjectRole.READER: 1,
    ProjectRole.EDITOR: 2,
    ProjectRole.OWNER: 3,
}


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    role: ProjectRole


async def get_project_access(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> ProjectAccess | None:
    project_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        return None

    if project.owner_id == user_id:
        return ProjectAccess(project=project, role=ProjectRole.OWNER)

    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        return None
    if member.role == "owner" and project.owner_id != user_id:
        return None
    try:
        role = ProjectRole(member.role)
    except ValueError:
        return None
    return ProjectAccess(project=project, role=role)


def has_required_role(actual: ProjectRole, required: ProjectRole) -> bool:
    return ROLE_RANK[actual] >= ROLE_RANK[required]


def _record_denial(request: object, project_id: object, user_id: object) -> None:
    """Note a refused access so an operator can see a probing pattern.

    The event log is best effort: a failure to record must not mask the refusal the
    caller is about to receive.
    """
    try:
        from app.security.guards import SecurityEventKind, current_event_log

        log = current_event_log(request)  # type: ignore[arg-type]
        log.record(
            SecurityEventKind.PERMISSION_DENIED,
            actor_id=str(user_id),
            project_id=str(project_id),
            outcome="blocked",
        )
    except Exception:  # noqa: BLE001 - logging must never break the refusal
        pass


async def authorize_project_access(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    required_role: ProjectRole,
    request: object | None = None,
) -> ProjectAccess:
    access = await get_project_access(
        db,
        project_id=project_id,
        user_id=user_id,
    )
    if access is None:
        # Do not reveal whether a project owned by another user exists.
        if request is not None:
            _record_denial(request, project_id, user_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    if not has_required_role(access.role, required_role):
        if request is not None:
            _record_denial(request, project_id, user_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return access


async def require_project_reader(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> ProjectAccess:
    return await authorize_project_access(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        required_role=ProjectRole.READER,
        request=request,
    )


async def require_project_editor(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> ProjectAccess:
    return await authorize_project_access(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        required_role=ProjectRole.EDITOR,
        request=request,
    )


async def require_project_owner(
    request: Request,
    project_id: UUID,
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> ProjectAccess:
    return await authorize_project_access(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        required_role=ProjectRole.OWNER,
        request=request,
    )
