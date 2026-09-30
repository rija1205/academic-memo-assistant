from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.source import Source, SourceBlock, SourceFile, SourcePage, SourceProcessingJob
from app.sources.extraction import (
    ExtractionError,
    ExtractionResult,
    NullOcrProvider,
    OcrProvider,
    extract_document,
)
from app.storage.base import StorageError, StorageProvider


def build_ocr_provider(settings: Settings) -> OcrProvider:
    if settings.source_ocr_provider in {"none", "", "disabled"}:
        return NullOcrProvider()
    raise ExtractionError(
        "Le fournisseur OCR configuré n'est pas disponible sur cette installation.",
        technical=f"Unsupported OCR provider: {settings.source_ocr_provider}",
    )


async def _set_stage(
    db: AsyncSession,
    *,
    source: Source,
    job: SourceProcessingJob,
    stage: str,
    progress: int,
) -> None:
    now = datetime.now(UTC)
    source.stage = stage
    source.progress = progress
    job.stage = stage
    job.progress = progress
    job.updated_at = now
    await db.commit()


async def _store_extraction(
    db: AsyncSession,
    *,
    source: Source,
    result: ExtractionResult,
) -> None:
    await db.execute(delete(SourceBlock).where(SourceBlock.source_id == source.id))
    await db.execute(delete(SourcePage).where(SourcePage.source_id == source.id))
    pages: list[SourcePage] = []
    for page in result.pages:
        db_page = SourcePage(
            source_id=source.id,
            page_number=page.page_number,
            text=page.text,
            char_count=len(page.text),
        )
        db.add(db_page)
        pages.append(db_page)
    await db.flush()
    page_ids = {page.page_number: page.id for page in pages}
    for page in result.pages:
        for block in page.blocks:
            db.add(
                SourceBlock(
                    source_id=source.id,
                    page_id=page_ids.get(page.page_number),
                    page_number=block.page_number,
                    block_index=block.block_index,
                    block_type=block.block_type,
                    text=block.text,
                    position_start=block.position_start,
                    position_end=block.position_end,
                    provenance_id=uuid4(),
                )
            )
    if source.title is None and result.metadata.title:
        source.title = result.metadata.title[:1000]
    if not source.authors and result.metadata.authors:
        source.authors = list(result.metadata.authors)
    source.page_count = result.page_count
    source.detected_language = result.metadata.detected_language
    source.updated_at = datetime.now(UTC)


async def mark_source_failed(
    db: AsyncSession,
    *,
    source_id: UUID,
    job_id: UUID | None,
    message: str,
    technical: str | None = None,
) -> Source | None:
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.deleted_at.is_(None))
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        return None
    job_result = await db.execute(
        select(SourceProcessingJob).where(
            SourceProcessingJob.source_id == source.id,
            *([SourceProcessingJob.id == job_id] if job_id else []),
        ).order_by(SourceProcessingJob.created_at.desc()).limit(1)
    )
    job = job_result.scalar_one_or_none()
    now = datetime.now(UTC)
    source.status = "failed"
    source.stage = "failed"
    source.error_message = message
    if job is not None:
        job.status = "failed"
        job.stage = "failed"
        job.error_message = technical or message
        job.finished_at = now
        job.updated_at = now
    await db.commit()
    return source


async def process_source(
    db: AsyncSession,
    *,
    source_id: UUID,
    storage: StorageProvider,
    settings: Settings,
    job_id: UUID | None = None,
    ocr_provider: OcrProvider | None = None,
) -> Source:
    source_result = await db.execute(
        select(Source)
        .where(Source.id == source_id, Source.deleted_at.is_(None))
        .with_for_update()
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise ExtractionError("Source not found.")
    file_result = await db.execute(select(SourceFile).where(SourceFile.source_id == source.id))
    source_file = file_result.scalar_one_or_none()
    if source_file is None:
        raise ExtractionError("Source file metadata is missing.")
    job_result = await db.execute(
        select(SourceProcessingJob)
        .where(
            SourceProcessingJob.source_id == source.id,
            *([SourceProcessingJob.id == job_id] if job_id else []),
        )
        .order_by(SourceProcessingJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        job = SourceProcessingJob(source_id=source.id)
        db.add(job)
        await db.flush()
    if job.status == "completed":
        return source
    now = datetime.now(UTC)
    source.status = "processing"
    source.stage = "validating"
    source.progress = 5
    source.error_message = None
    job.status = "running"
    job.stage = "validating"
    job.progress = 5
    job.attempts += 1
    job.started_at = now
    job.finished_at = None
    job.updated_at = now
    await db.commit()

    try:
        data = storage.read(source_file.storage_key)
        await _set_stage(db, source=source, job=job, stage="extracting", progress=30)
        result = extract_document(
            data,
            mime_type=source.mime_type,
            extension=source.extension,
            ocr_provider=ocr_provider or build_ocr_provider(settings),
        )
        await _set_stage(db, source=source, job=job, stage="enriching", progress=80)
        await _store_extraction(db, source=source, result=result)
        finished = datetime.now(UTC)
        source.status = "processed"
        source.stage = "done"
        source.progress = 100
        source.error_message = None
        job.status = "completed"
        job.stage = "done"
        job.progress = 100
        job.finished_at = finished
        job.updated_at = finished
        await db.commit()
        await db.refresh(source)
        return source
    except (ExtractionError, StorageError, SQLAlchemyError) as exc:
        await db.rollback()
        source_result = await db.execute(select(Source).where(Source.id == source.id))
        source = source_result.scalar_one()
        job_result = await db.execute(
            select(SourceProcessingJob).where(SourceProcessingJob.id == job.id)
        )
        job = job_result.scalar_one()
        message = exc.message if isinstance(exc, ExtractionError) else str(exc)
        technical = exc.technical if isinstance(exc, ExtractionError) else str(exc)
        source.status = "failed"
        source.stage = "failed"
        source.error_message = message
        job.status = "failed"
        job.stage = "failed"
        job.error_message = technical
        job.finished_at = datetime.now(UTC)
        job.updated_at = datetime.now(UTC)
        await db.commit()
        return source
