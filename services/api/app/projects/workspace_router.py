from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.db.session import get_session
from app.projects.access import (
    ProjectAccess,
    ProjectRole,
    require_project_editor,
    require_project_owner,
    require_project_reader,
)
from app.projects.schemas import (
    DuplicateProjectRequest,
    OutlineNodeCreateRequest,
    OutlineNodeResponse,
    OutlineNodeUpdateRequest,
    OutlineReorderRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    RestoreRevisionRequest,
    SectionContentUpdateRequest,
    SectionResponse,
    SectionRevisionResponse,
)
from app.projects.service import (
    archive_project,
    create_outline_node,
    create_project,
    delete_outline_node,
    delete_project,
    duplicate_outline_node,
    duplicate_project,
    get_section_content,
    list_outline,
    list_section_revisions,
    project_response,
    reorder_outline,
    restore_section_revision,
    save_section_content,
    update_outline_node,
    update_project,
)

router = APIRouter(prefix="/api/projects", tags=["project-workspace"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    payload: ProjectCreateRequest,
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> ProjectResponse:
    project = await create_project(db, owner_id=current_auth.user.id, payload=payload)
    return await project_response(db, project, access_role="owner")


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project_endpoint(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> ProjectResponse:
    if (
        payload.status is not None
        and access.role != ProjectRole.OWNER
        and payload.status != access.project.status
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project owner can change the project status.",
        )
    project = await update_project(db, project=access.project, payload=payload)
    return await project_response(db, project, access_role=access.role.value)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project_endpoint(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> ProjectResponse:
    project = await archive_project(db, project=access.project)
    return await project_response(db, project, access_role=access.role.value)


@router.post("/{project_id}/duplicate", response_model=ProjectResponse, status_code=201)
async def duplicate_project_endpoint(
    project_id: UUID,
    payload: DuplicateProjectRequest,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> ProjectResponse:
    project = await duplicate_project(
        db,
        project=access.project,
        new_owner_id=current_auth.user.id,
        title=payload.title,
    )
    return await project_response(db, project, access_role="owner")


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    await delete_project(db, project=access.project)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/outline", response_model=list[OutlineNodeResponse])
async def get_project_outline(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> list[OutlineNodeResponse]:
    return await list_outline(db, project_id=access.project.id)


@router.post("/{project_id}/outline", response_model=OutlineNodeResponse, status_code=201)
async def create_outline_node_endpoint(
    project_id: UUID,
    payload: OutlineNodeCreateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> OutlineNodeResponse:
    return await create_outline_node(
        db,
        project_id=access.project.id,
        created_by=current_auth.user.id,
        payload=payload,
    )


@router.post("/{project_id}/outline/reorder", response_model=list[OutlineNodeResponse])
async def reorder_outline_endpoint(
    project_id: UUID,
    payload: OutlineReorderRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> list[OutlineNodeResponse]:
    return await reorder_outline(db, project_id=access.project.id, moves=payload.moves)


@router.patch("/{project_id}/outline/{node_id}", response_model=OutlineNodeResponse)
async def update_outline_node_endpoint(
    project_id: UUID,
    node_id: UUID,
    payload: OutlineNodeUpdateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> OutlineNodeResponse:
    return await update_outline_node(
        db,
        project_id=access.project.id,
        node_id=node_id,
        payload=payload,
    )


@router.post(
    "/{project_id}/outline/{node_id}/duplicate",
    response_model=OutlineNodeResponse,
    status_code=201,
)
async def duplicate_outline_node_endpoint(
    project_id: UUID,
    node_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> OutlineNodeResponse:
    return await duplicate_outline_node(
        db,
        project_id=access.project.id,
        node_id=node_id,
        created_by=current_auth.user.id,
    )


@router.delete("/{project_id}/outline/{node_id}", status_code=204)
async def delete_outline_node_endpoint(
    project_id: UUID,
    node_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    await delete_outline_node(db, project_id=access.project.id, node_id=node_id)
    return Response(status_code=204)


@router.get("/{project_id}/sections/{section_id}", response_model=SectionResponse)
async def get_section_endpoint(
    project_id: UUID,
    section_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SectionResponse:
    return await get_section_content(db, project_id=access.project.id, section_id=section_id)


@router.put("/{project_id}/sections/{section_id}/content", response_model=SectionResponse)
async def save_section_endpoint(
    project_id: UUID,
    section_id: UUID,
    payload: SectionContentUpdateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> SectionResponse:
    return await save_section_content(
        db,
        project_id=access.project.id,
        section_id=section_id,
        user_id=current_auth.user.id,
        payload=payload,
    )


@router.get(
    "/{project_id}/sections/{section_id}/revisions",
    response_model=list[SectionRevisionResponse],
)
async def list_section_revisions_endpoint(
    project_id: UUID,
    section_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> list[SectionRevisionResponse]:
    return await list_section_revisions(db, project_id=access.project.id, section_id=section_id)


@router.post(
    "/{project_id}/sections/{section_id}/revisions/{revision_id}/restore",
    response_model=SectionResponse,
)
async def restore_section_revision_endpoint(
    project_id: UUID,
    section_id: UUID,
    revision_id: UUID,
    payload: RestoreRevisionRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> SectionResponse:
    return await restore_section_revision(
        db,
        project_id=access.project.id,
        section_id=section_id,
        revision_id=revision_id,
        user_id=current_auth.user.id,
        change_summary=payload.change_summary,
    )
