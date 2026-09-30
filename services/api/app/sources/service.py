from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.normalize import (
    normalize_doi as _normalize_doi,
)
from app.core.normalize import (
    normalize_tag as _normalize_tag,
)
from app.core.normalize import (
    normalize_title as _normalize_title,
)
from app.models.source import (
    Source,
    SourceBlock,
    SourceFile,
    SourceFolder,
    SourcePage,
    SourceProcessingJob,
    SourceTag,
)
from app.sources.schemas import (
    SourceBlockResponse,
    SourceDuplicateResponse,
    SourceFolderRequest,
    SourceFolderResponse,
    SourceJobResponse,
    SourceListResponse,
    SourceMetadataUpdate,
    SourcePageResponse,
    SourcePreviewResponse,
    SourceResponse,
    SourceSearchResponse,
    SourceSearchResult,
)

# The canonical DOI, title and tag forms now live in app.core.normalize so the source
# library (stage 5) and the bibliography (stage 9) compare metadata identically. They are
# re-exported here because the existing importers expect them from this module.
normalize_doi = _normalize_doi
normalize_title = _normalize_title
normalize_tag = _normalize_tag


def _job_response(job: SourceProcessingJob | None) -> SourceJobResponse | None:
    if job is None:
        return None
    return SourceJobResponse(
        id=job.id,
        source_id=job.source_id,
        task_id=job.task_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        attempts=job.attempts,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _tags_for_source(db: AsyncSession, source_id: UUID) -> list[str]:
    result = await db.execute(
        select(SourceTag.name)
        .where(SourceTag.source_id == source_id)
        .order_by(SourceTag.normalized_name.asc())
    )
    return list(result.scalars().all())


async def _latest_job(db: AsyncSession, source_id: UUID) -> SourceProcessingJob | None:
    result = await db.execute(
        select(SourceProcessingJob)
        .where(SourceProcessingJob.source_id == source_id)
        .order_by(SourceProcessingJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def source_response(
    db: AsyncSession,
    source: Source,
    *,
    duplicate: SourceDuplicateResponse | None = None,
) -> SourceResponse:
    tags = await _tags_for_source(db, source.id)
    job = await _latest_job(db, source.id)
    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        folder_id=source.folder_id,
        original_filename=source.original_filename,
        extension=source.extension,
        mime_type=source.mime_type,
        size_bytes=source.size_bytes,
        sha256=source.sha256,
        status=source.status,
        stage=source.stage,
        progress=source.progress,
        error_message=source.error_message,
        title=source.title,
        authors=source.authors or [],
        publication_year=source.publication_year,
        doi=source.doi,
        url=source.url,
        journal=source.journal,
        volume=source.volume,
        issue=source.issue,
        pages=source.pages,
        publisher=source.publisher,
        publication_type=source.publication_type,
        abstract=source.abstract,
        keywords=source.keywords or [],
        detected_language=source.detected_language,
        page_count=source.page_count,
        imported_at=source.imported_at,
        created_at=source.created_at,
        updated_at=source.updated_at,
        tags=tags,
        duplicate_of=duplicate.source_id if duplicate else None,
        duplicate_reason=duplicate.reason if duplicate else None,
        job_id=job.id if job else None,
    )


async def get_source(
    db: AsyncSession,
    *,
    project_id: UUID,
    source_id: UUID,
    include_deleted: bool = False,
) -> Source:
    statement = select(Source).where(Source.id == source_id, Source.project_id == project_id)
    if not include_deleted:
        statement = statement.where(Source.deleted_at.is_(None))
    result = await db.execute(statement)
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source


async def get_source_file(db: AsyncSession, source_id: UUID) -> SourceFile:
    result = await db.execute(select(SourceFile).where(SourceFile.source_id == source_id))
    source_file = result.scalar_one_or_none()
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source file not found.")
    return source_file


async def find_duplicate_by_hash(
    db: AsyncSession,
    *,
    project_id: UUID,
    sha256: str,
    exclude_source_id: UUID | None = None,
) -> Source | None:
    statement = select(Source).where(
        Source.project_id == project_id,
        Source.sha256 == sha256,
        Source.deleted_at.is_(None),
    )
    if exclude_source_id:
        statement = statement.where(Source.id != exclude_source_id)
    result = await db.execute(statement.limit(1))
    return result.scalar_one_or_none()


async def find_academic_duplicates(
    db: AsyncSession,
    *,
    source: Source,
    limit: int = 10,
) -> list[Source]:
    conditions = []
    if source.doi:
        conditions.append(Source.doi == normalize_doi(source.doi))
    if source.title:
        conditions.append(func.lower(Source.title) == normalize_title(source.title))
    if not conditions:
        return []
    result = await db.execute(
        select(Source)
        .where(
            Source.project_id == source.project_id,
            Source.id != source.id,
            Source.deleted_at.is_(None),
            or_(*conditions),
        )
        .order_by(Source.imported_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_sources(
    db: AsyncSession,
    *,
    project_id: UUID,
    q: str | None = None,
    status_filter: str | None = None,
    publication_type: str | None = None,
    folder_id: UUID | None = None,
    tag: str | None = None,
    year: int | None = None,
    sort: str = "imported_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> SourceListResponse:
    filters = [Source.project_id == project_id, Source.deleted_at.is_(None)]
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Source.title.ilike(pattern),
                Source.original_filename.ilike(pattern),
                Source.doi.ilike(pattern),
                Source.journal.ilike(pattern),
                func.cast(Source.authors, String).ilike(pattern),
            )
        )
    if status_filter:
        filters.append(Source.status == status_filter)
    if publication_type:
        filters.append(Source.publication_type == publication_type)
    if folder_id:
        filters.append(Source.folder_id == folder_id)
    if year:
        filters.append(Source.publication_year == year)
    tag_join = None
    if tag:
        tag_join = SourceTag
        filters.append(SourceTag.normalized_name == normalize_tag(tag))

    sort_column = {
        "imported_at": Source.imported_at,
        "updated_at": Source.updated_at,
        "title": Source.title,
        "publication_year": Source.publication_year,
        "status": Source.status,
    }.get(sort, Source.imported_at)
    direction = sort_column.asc() if order == "asc" else sort_column.desc()
    statement = select(Source).where(*filters)
    count_statement = select(func.count(func.distinct(Source.id))).where(*filters)
    if tag_join is not None:
        statement = statement.join(SourceTag, SourceTag.source_id == Source.id)
        count_statement = count_statement.join(SourceTag, SourceTag.source_id == Source.id)
    total = int((await db.execute(count_statement)).scalar_one())
    result = await db.execute(
        statement.order_by(direction, Source.id.asc()).limit(limit).offset(offset)
    )
    items = [await source_response(db, source) for source in result.scalars().all()]
    return SourceListResponse(items=items, total=total, limit=limit, offset=offset)


async def create_folder(
    db: AsyncSession,
    *,
    project_id: UUID,
    payload: SourceFolderRequest,
) -> SourceFolderResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty.")
    folder = SourceFolder(
        project_id=project_id,
        name=name,
        normalized_name=normalize_tag(name),
    )
    db.add(folder)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Folder already exists.") from exc
    await db.refresh(folder)
    return SourceFolderResponse(
        id=folder.id,
        project_id=folder.project_id,
        name=folder.name,
        created_at=folder.created_at,
    )


async def list_folders(db: AsyncSession, *, project_id: UUID) -> list[SourceFolderResponse]:
    result = await db.execute(
        select(SourceFolder, func.count(Source.id))
        .outerjoin(Source, Source.folder_id == SourceFolder.id)
        .where(
            SourceFolder.project_id == project_id,
            or_(Source.id.is_(None), Source.deleted_at.is_(None)),
        )
        .group_by(SourceFolder.id)
        .order_by(SourceFolder.normalized_name.asc())
    )
    return [
        SourceFolderResponse(
            id=folder.id,
            project_id=folder.project_id,
            name=folder.name,
            created_at=folder.created_at,
            source_count=count,
        )
        for folder, count in result.all()
    ]


async def _replace_tags(
    db: AsyncSession,
    *,
    source: Source,
    project_id: UUID,
    tags: list[str] | None,
) -> None:
    if tags is None:
        return
    await db.execute(delete(SourceTag).where(SourceTag.source_id == source.id))
    seen: set[str] = set()
    for raw_tag in tags:
        name = raw_tag.strip()
        normalized = normalize_tag(name)
        if not name or len(name) > 80 or normalized in seen:
            continue
        seen.add(normalized)
        db.add(
            SourceTag(
                source_id=source.id,
                project_id=project_id,
                name=name,
                normalized_name=normalized,
            )
        )


async def update_source_metadata(
    db: AsyncSession,
    *,
    project_id: UUID,
    source: Source,
    payload: SourceMetadataUpdate,
) -> SourceResponse:
    values = payload.model_dump(exclude_unset=True)
    for field in (
        "title",
        "doi",
        "url",
        "journal",
        "volume",
        "issue",
        "pages",
        "publisher",
        "abstract",
    ):
        if field in values:
            value = values[field]
            if isinstance(value, str):
                value = value.strip() or None
            if field == "doi":
                value = normalize_doi(value)
            setattr(source, field, value)
    if "authors" in values:
        source.authors = [item.strip() for item in (values["authors"] or []) if item.strip()]
    if "keywords" in values:
        source.keywords = [item.strip() for item in (values["keywords"] or []) if item.strip()]
    if "publication_year" in values:
        source.publication_year = values["publication_year"]
    if "publication_type" in values:
        source.publication_type = values["publication_type"]
    if "folder_id" in values:
        if values["folder_id"] is not None:
            folder_result = await db.execute(
                select(SourceFolder).where(
                    SourceFolder.id == values["folder_id"],
                    SourceFolder.project_id == project_id,
                )
            )
            if folder_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=422, detail="Folder not found in this project.")
        source.folder_id = values["folder_id"]
    await _replace_tags(db, source=source, project_id=project_id, tags=values.get("tags"))
    source.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(source)
    duplicates = await find_academic_duplicates(db, source=source)
    duplicate = None
    if duplicates:
        reason = "doi" if source.doi and duplicates[0].doi == normalize_doi(source.doi) else "title"
        duplicate = SourceDuplicateResponse(
            source_id=duplicates[0].id,
            sha256=duplicates[0].sha256,
            title=duplicates[0].title,
            reason=reason,
        )
    return await source_response(db, source, duplicate=duplicate)


async def create_processing_job(
    db: AsyncSession,
    *,
    source: Source,
) -> SourceProcessingJob:
    job = SourceProcessingJob(source_id=source.id, status="queued", stage="queued")
    db.add(job)
    source.status = "processing"
    source.stage = "queued"
    source.progress = 0
    source.error_message = None
    await db.flush()
    return job


async def list_jobs(db: AsyncSession, *, source_id: UUID) -> list[SourceJobResponse]:
    result = await db.execute(
        select(SourceProcessingJob)
        .where(SourceProcessingJob.source_id == source_id)
        .order_by(SourceProcessingJob.created_at.desc())
    )
    return [_job_response(job) for job in result.scalars().all() if job is not None]


async def get_preview(
    db: AsyncSession,
    *,
    project_id: UUID,
    source_id: UUID,
) -> SourcePreviewResponse:
    source = await get_source(db, project_id=project_id, source_id=source_id)
    pages_result = await db.execute(
        select(SourcePage)
        .where(SourcePage.source_id == source.id)
        .order_by(SourcePage.page_number.asc())
    )
    pages = list(pages_result.scalars().all())
    blocks_result = await db.execute(
        select(SourceBlock)
        .where(SourceBlock.source_id == source.id)
        .order_by(SourceBlock.page_number.asc(), SourceBlock.block_index.asc())
    )
    blocks_by_page: dict[int, list[SourceBlock]] = {}
    for block in blocks_result.scalars().all():
        blocks_by_page.setdefault(block.page_number, []).append(block)
    page_responses = [
        SourcePageResponse(
            id=page.id,
            source_id=page.source_id,
            page_number=page.page_number,
            text=page.text,
            char_count=page.char_count,
            blocks=[
                SourceBlockResponse(
                    id=block.id,
                    source_id=block.source_id,
                    page_id=block.page_id,
                    page_number=block.page_number,
                    block_index=block.block_index,
                    block_type=block.block_type,
                    text=block.text,
                    position_start=block.position_start,
                    position_end=block.position_end,
                    provenance_id=block.provenance_id,
                )
                for block in blocks_by_page.get(page.page_number, [])
            ],
        )
        for page in pages
    ]
    return SourcePreviewResponse(
        source=await source_response(db, source),
        pages=page_responses,
        warnings=[],
        ocr_used=False,
        sheets=[],
    )


async def search_sources(
    db: AsyncSession,
    *,
    project_id: UUID,
    query: str,
    limit: int = 100,
) -> SourceSearchResponse:
    cleaned = query.strip()
    if not cleaned:
        return SourceSearchResponse(query=query, results=[], total=0)
    pattern = f"%{cleaned.replace('%', r'\%').replace('_', r'\_')}%"
    result = await db.execute(
        select(SourceBlock, Source)
        .join(Source, Source.id == SourceBlock.source_id)
        .where(
            Source.project_id == project_id,
            Source.deleted_at.is_(None),
            Source.status == "processed",
            SourceBlock.text.ilike(pattern, escape="\\"),
        )
        .order_by(
            Source.updated_at.desc(),
            SourceBlock.page_number.asc(),
            SourceBlock.block_index.asc(),
        )
        .limit(limit)
    )
    rows = result.all()
    search_results: list[SourceSearchResult] = []
    lowered = cleaned.casefold()
    for block, source in rows:
        match_start = block.text.casefold().find(lowered)
        if match_start < 0:
            match_start = 0
        match_end = min(len(block.text), match_start + len(cleaned))
        left = max(0, match_start - 80)
        right = min(len(block.text), match_end + 80)
        snippet = block.text[left:right]
        search_results.append(
            SourceSearchResult(
                source_id=source.id,
                source_title=source.title or source.original_filename,
                original_filename=source.original_filename,
                page_number=block.page_number,
                block_index=block.block_index,
                provenance_id=block.provenance_id,
                snippet=snippet,
                match_start=match_start,
                match_end=match_end,
            )
        )
    return SourceSearchResponse(query=query, results=search_results, total=len(search_results))
