from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.dependencies import CurrentAuth, get_current_auth
from app.db.session import get_session
from app.models.project import Project, ProjectMember
from app.projects.access import ProjectAccess, ProjectRole, require_project_reader
from app.projects.schemas import ProjectAccessResponse, ProjectResponse, ProjectSummaryResponse
from app.projects.service import project_response

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummaryResponse])
async def list_projects(
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> list[ProjectSummaryResponse]:
    member_alias = aliased(ProjectMember)
    result = await db.execute(
        select(Project, member_alias.role)
        .outerjoin(
            member_alias,
            and_(
                member_alias.project_id == Project.id,
                member_alias.user_id == current_auth.user.id,
            ),
        )
        .where(
            Project.deleted_at.is_(None),
            or_(
                Project.owner_id == current_auth.user.id,
                member_alias.user_id == current_auth.user.id,
            ),
        )
        .order_by(Project.updated_at.desc())
    )

    projects: list[ProjectSummaryResponse] = []
    for project, member_role in result.all():
        raw_role = ProjectRole.OWNER if project.owner_id == current_auth.user.id else member_role
        if raw_role == "owner" and project.owner_id != current_auth.user.id:
            continue
        try:
            role = ProjectRole(raw_role)
        except ValueError:
            continue
        projects.append(await project_response(db, project, access_role=role.value))
    return projects


@router.get("/{project_id}/access", response_model=ProjectAccessResponse)
async def get_project_access_role(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
) -> ProjectAccessResponse:
    return ProjectAccessResponse(project_id=project_id, role=access.role.value)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    return await project_response(db, access.project, access_role=access.role.value)
