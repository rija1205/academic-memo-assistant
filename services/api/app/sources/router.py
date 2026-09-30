from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.source import Source, SourceFile, SourceFolder, SourceProcessingJob, SourceTag
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_owner,
    require_project_reader,
)
from app.rag.autoindex import schedule_indexing
from app.rag.pipeline import deindex_source
from app.sources.dependencies import get_source_storage, require_worker_token
from app.sources.dispatch import enqueue_source_processing
from app.sources.processing import mark_source_failed, process_source
from app.sources.schemas import (
    SourceDuplicateResponse,
    SourceFolderRequest,
    SourceFolderResponse,
    SourceJobResponse,
    SourceListResponse,
    SourceMetadataUpdate,
    SourcePreviewResponse,
    SourceResponse,
    SourceSearchResponse,
    SourceUploadResponse,
)
from app.sources.service import (
    create_folder,
    create_processing_job,
    find_academic_duplicates,
    find_duplicate_by_hash,
    get_preview,
    get_source,
    get_source_file,
    list_folders,
    list_jobs,
    list_sources,
    normalize_doi,
    search_sources,
    source_response,
    update_source_metadata,
)
from app.sources.validation import UploadValidationError, validate_upload
from app.storage import StorageError, StorageProvider

router = APIRouter(prefix="/api", tags=["sources"])


def _duplicate_response(source: Source, reason: str) -> SourceDuplicateResponse:
    return SourceDuplicateResponse(
        source_id=source.id,
        sha256=source.sha256,
        title=source.title,
        reason=reason,
    )


async def _dispatch_or_process(
    db: AsyncSession,
    *,
    source: Source,
    job: SourceProcessingJob,
    settings: Settings,
    storage: StorageProvider,
) -> None:
    if settings.source_processing_mode == "sync":
        await process_source(
            db,
            source_id=source.id,
            storage=storage,
            settings=settings,
            job_id=job.id,
        )
        await schedule_indexing(db, source=source, settings=settings)
        return
    try:
        task_id = enqueue_source_processing(
            source_id=source.id,
            job_id=job.id,
            settings=settings,
        )
    except Exception as exc:
        source.status = "failed"
        source.stage = "failed"
        source.error_message = "Le service de traitement est indisponible."
        job.status = "failed"
        job.stage = "failed"
        job.error_message = str(exc)
        await db.commit()
        return
    if task_id:
        job.task_id = task_id
        await db.commit()


@router.post(
    "/projects/{project_id}/sources/upload",
    response_model=SourceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    project_id: UUID,
    file: UploadFile = File(...),
    allow_duplicate: bool = Form(False),
    folder_id: UUID | None = Form(None),
    tags: str = Form(""),
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
    storage: StorageProvider = Depends(get_source_storage),
    _: None = Depends(require_csrf),
) -> SourceUploadResponse:
    if folder_id is not None:
        folder_result = await db.execute(
            select(SourceFolder).where(
                SourceFolder.id == folder_id,
                SourceFolder.project_id == project_id,
            )
        )
        if folder_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=422, detail="Folder not found in this project.")
    try:
        data = await file.read(settings.source_max_upload_bytes + 1)
        validated = validate_upload(
            filename=file.filename,
            declared_mime=file.content_type,
            data=data,
            max_size_bytes=settings.source_max_upload_bytes,
        )
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    duplicate = await find_duplicate_by_hash(
        db,
        project_id=project_id,
        sha256=validated.sha256,
    )
    if duplicate is not None and not allow_duplicate:
        detail = {
            "code": "duplicate_file",
            "message": "Ce fichier identique existe déjà dans ce projet.",
            "duplicate": _duplicate_response(duplicate, "sha256").model_dump(mode="json"),
        }
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    source_id = uuid4()
    storage_key = (
        f"projects/{project_id}/sources/{source_id}/{validated.safe_filename}"
    )
    try:
        storage.save(storage_key, validated.data, content_type=validated.mime_type)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Le stockage du fichier a échoué.") from exc
    source = Source(
        id=source_id,
        project_id=project_id,
        uploaded_by=current_auth.user.id,
        folder_id=folder_id,
        original_filename=validated.original_filename,
        extension=validated.extension,
        mime_type=validated.mime_type,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        status="uploaded",
        stage="queued",
    )
    db.add(source)
    db.add(
        SourceFile(
            source_id=source.id,
            storage_provider=storage.name,
            storage_key=storage_key,
            original_filename=validated.original_filename,
            mime_type=validated.mime_type,
            size_bytes=validated.size_bytes,
            sha256=validated.sha256,
        )
    )
    seen_tags: set[str] = set()
    for raw_tag in tags.split(","):
        tag_name = raw_tag.strip()
        normalized = tag_name.casefold()
        if tag_name and len(tag_name) <= 80 and normalized not in seen_tags:
            seen_tags.add(normalized)
            db.add(
                SourceTag(
                    source_id=source.id,
                    project_id=project_id,
                    name=tag_name,
                    normalized_name=normalized,
                )
            )
    job = await create_processing_job(db, source=source)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            storage.delete(storage_key)
        except StorageError:
            pass
        raise
    await _dispatch_or_process(
        db,
        source=source,
        job=job,
        settings=settings,
        storage=storage,
    )
    source = await get_source(db, project_id=project_id, source_id=source.id)
    return SourceUploadResponse(
        source=await source_response(db, source),
        duplicate=_duplicate_response(duplicate, "sha256") if duplicate else None,
    )


@router.get("/projects/{project_id}/sources", response_model=SourceListResponse)
async def list_project_sources(
    project_id: UUID,
    q: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status"),
    publication_type: str | None = Query(default=None, max_length=64),
    folder_id: UUID | None = None,
    tag: str | None = Query(default=None, max_length=80),
    year: int | None = Query(default=None, ge=1000, le=3000),
    sort: str = Query(default="imported_at"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SourceListResponse:
    return await list_sources(
        db,
        project_id=project_id,
        q=q,
        status_filter=status_filter,
        publication_type=publication_type,
        folder_id=folder_id,
        tag=tag,
        year=year,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/sources/search", response_model=SourceSearchResponse)
async def search_project_sources(
    project_id: UUID,
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SourceSearchResponse:
    return await search_sources(db, project_id=project_id, query=q, limit=limit)


@router.get("/projects/{project_id}/sources/folders", response_model=list[SourceFolderResponse])
async def get_source_folders(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> list[SourceFolderResponse]:
    return await list_folders(db, project_id=project_id)


@router.post(
    "/projects/{project_id}/sources/folders",
    response_model=SourceFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_folder(
    project_id: UUID,
    payload: SourceFolderRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> SourceFolderResponse:
    return await create_folder(db, project_id=project_id, payload=payload)


@router.delete("/projects/{project_id}/sources/folders/{folder_id}", status_code=204)
async def delete_source_folder(
    project_id: UUID,
    folder_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    result = await db.execute(
        select(SourceFolder).where(
            SourceFolder.id == folder_id,
            SourceFolder.project_id == project_id,
        )
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    # Move sources to the root before deleting the folder.
    await db.execute(
        update(Source)
        .where(Source.folder_id == folder_id, Source.project_id == project_id)
        .values(folder_id=None)
    )
    await db.delete(folder)
    await db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/sources/{source_id}", response_model=SourceResponse)
async def get_source_detail(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SourceResponse:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    return await source_response(db, source)


@router.get(
    "/projects/{project_id}/sources/{source_id}/duplicates",
    response_model=list[SourceDuplicateResponse],
)
async def list_source_duplicates(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> list[SourceDuplicateResponse]:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    duplicates = await find_academic_duplicates(db, source=source)
    return [
        _duplicate_response(
            duplicate,
            "doi" if source.doi and duplicate.doi == normalize_doi(source.doi) else "title",
        )
        for duplicate in duplicates
    ]


@router.patch("/projects/{project_id}/sources/{source_id}", response_model=SourceResponse)
async def patch_source(
    project_id: UUID,
    source_id: UUID,
    payload: SourceMetadataUpdate,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> SourceResponse:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    return await update_source_metadata(
        db,
        project_id=project_id,
        source=source,
        payload=payload,
    )


@router.delete("/projects/{project_id}/sources/{source_id}", status_code=204)
async def delete_source(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    storage: StorageProvider = Depends(get_source_storage),
    _: None = Depends(require_csrf),
) -> Response:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    source_file = await get_source_file(db, source.id)
    try:
        storage.delete(source_file.storage_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="La suppression du fichier a échoué.") from exc

    # Desindex immediately: the chunks must never be returned by a search again.
    await deindex_source(db, source_id=source.id)
    source.deleted_at = datetime.now(UTC)
    source.updated_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/sources/{source_id}/download")
async def download_source(
    project_id: UUID,
    source_id: UUID,
    preview: bool = Query(default=False),
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    storage: StorageProvider = Depends(get_source_storage),
) -> Response:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    source_file = await get_source_file(db, source.id)
    try:
        data = storage.read(source_file.storage_key)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail="Le fichier source est introuvable.") from exc
    filename = quote(source.original_filename)
    disposition = "inline" if preview else "attachment"
    return Response(
        content=data,
        media_type=source.mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
            "X-Content-SHA256": source.sha256,
        },
    )


@router.get(
    "/projects/{project_id}/sources/{source_id}/preview",
    response_model=SourcePreviewResponse,
)
async def preview_source(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SourcePreviewResponse:
    return await get_preview(db, project_id=project_id, source_id=source_id)


@router.get(
    "/projects/{project_id}/sources/{source_id}/jobs",
    response_model=list[SourceJobResponse],
)
async def get_source_jobs(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> list[SourceJobResponse]:
    await get_source(db, project_id=project_id, source_id=source_id)
    return await list_jobs(db, source_id=source_id)


@router.post("/projects/{project_id}/sources/{source_id}/reprocess", response_model=SourceResponse)
async def reprocess_source(
    project_id: UUID,
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: StorageProvider = Depends(get_source_storage),
    _: None = Depends(require_csrf),
) -> SourceResponse:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    job = await create_processing_job(db, source=source)
    await db.commit()
    await _dispatch_or_process(db, source=source, job=job, settings=settings, storage=storage)
    source = await get_source(db, project_id=project_id, source_id=source_id)
    await schedule_indexing(db, source=source, settings=settings)
    return await source_response(db, source)


@router.post("/internal/sources/{source_id}/fail", response_model=SourceResponse)
async def internal_fail_source(
    source_id: UUID,
    job_id: UUID | None = None,
    message: str = Query(default="Le traitement de la source a échoué.", max_length=500),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_worker_token),
) -> SourceResponse:
    source = await mark_source_failed(
        db,
        source_id=source_id,
        job_id=job_id,
        message=message,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return await source_response(db, source)


@router.post("/internal/sources/{source_id}/process", response_model=SourceResponse)
async def internal_process_source(
    source_id: UUID,
    job_id: UUID | None = None,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: StorageProvider = Depends(get_source_storage),
    _: None = Depends(require_worker_token),
) -> SourceResponse:
    source = await process_source(
        db,
        source_id=source_id,
        storage=storage,
        settings=settings,
        job_id=job_id,
    )
    await schedule_indexing(db, source=source, settings=settings)
    return await source_response(db, source)
