"""Export orchestration: naming, rendering and the audit trace.

The renderer is chosen here, and only here. Everything above this module works with the
neutral document model, and everything below it is a specific library.
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.export.docx import render_docx
from app.export.options import (
    EXPORT_FORMATS,
    MAX_OUTPUT_BYTES,
    ExportOptionError,
    ExportOptions,
)
from app.export.pdf import render_pdf
from app.export.schemas import ExportRecordResponse
from app.export.service import build_document_model, load_sections
from app.models.export import DocumentExport

#: Characters kept in a file name. Everything else is replaced by a dash.
_UNSAFE = re.compile(r"[^A-Za-z0-9 _\-\.]+")
_SPACES = re.compile(r"\s+")

#: A name never exceeds this length, so the filesystem and the browser both stay happy.
MAX_NAME_STEM = 80


class ExportError(RuntimeError):
    """Raised when an export cannot be produced."""


def build_file_name(
    project_title: str, author: str | None, year: str | None, extension: str
) -> str:
    """``Titre_du_memoire_Auteur_2026.pdf``.

    The name is sanitised rather than trusted: a title may contain a slash, a quote or a
    control character, and a header must never be able to inject one.
    """

    def clean(value: str | None) -> str:
        if not value:
            return ""
        text = unicodedata.normalize("NFKD", value)
        text = "".join(char for char in text if not unicodedata.combining(char))
        text = _UNSAFE.sub("-", text)
        text = _SPACES.sub("_", text.strip())
        return text.strip("-_.")[:40]

    year_part = clean(year) if year else ""
    if year_part and not year_part.isdigit():
        # Keep only the digits of an academic year such as "2025-2026".
        digits = re.sub(r"[^0-9]", "", year_part)
        year_part = digits[:8] if digits else ""
    parts = [part for part in (clean(project_title), clean(author), year_part) if part]
    stem = "_".join(parts) or "memoire"
    return f"{stem[:MAX_NAME_STEM]}.{extension}"


def _serialisable_options(options: ExportOptions) -> dict[str, Any]:
    return {
        "page_size": options.page_size,
        "orientation": options.orientation,
        "font_family": options.font_family,
        "font_size": options.font_size,
        "line_spacing": options.line_spacing,
        "include_cover": options.include_cover,
        "include_toc": options.include_toc,
        "include_bibliography": options.include_bibliography,
        "include_annexes": options.include_annexes,
        "number_headings": options.number_headings,
        "embed_remote_images": options.embed_remote_images,
    }


async def record_export(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID | None,
    export_format: str,
    file_name: str,
    payload: bytes,
    model: Any,
    options: ExportOptions,
    duration_ms: int,
) -> DocumentExport:
    """Write the export trace. No memoir content is stored."""
    if export_format not in EXPORT_FORMATS:
        raise ExportError(f"Format d'export inconnu : {export_format}.")
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ExportError(
            "Le document généré dépasse la taille maximale autorisée pour un export."
        )
    record = DocumentExport(
        project_id=project_id,
        user_id=user_id,
        format=export_format,
        file_name=file_name,
        size_bytes=len(payload),
        style=model.style,
        style_label=model.style_label,
        section_count=len(model.section_titles),
        figure_count=model.figure_count,
        table_count=model.table_count,
        citation_count=model.citation_count,
        uncited_count=model.uncited_count,
        orphan_count=model.orphan_count,
        warnings=list(model.warnings),
        options=_serialisable_options(options),
        duration_ms=duration_ms,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


def render_document(model: Any, options: ExportOptions, export_format: str) -> bytes:
    """Render with the library that matches the format."""
    if export_format == "pdf":
        return render_pdf(model, options)
    if export_format == "docx":
        return render_docx(model, options)
    raise ExportError(f"Format d'export non pris en charge : {export_format}.")


async def generate_export(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    export_format: str,
    options: ExportOptions,
) -> tuple[bytes, str, DocumentExport]:
    """Build, render and record one export. Returns ``(payload, file_name, record)``."""
    if export_format not in EXPORT_FORMATS:
        raise ExportError(f"Format d'export non pris en charge : {export_format}.")
    started = time.perf_counter()
    try:
        model = await build_document_model(db, project_id=project_id, options=options)
    except LookupError:
        raise
    except ExportOptionError:
        raise
    except ValueError as exc:
        raise ExportError(str(exc)) from exc

    project = getattr(model, "project_title", "") or "memoire"
    author = model.cover.author if model.cover else None
    year = model.cover.academic_year if model.cover else None
    file_name = build_file_name(
        project, author, year, EXPORT_FORMATS[export_format]["extension"]
    )
    payload = render_document(model, options, export_format)
    duration = int((time.perf_counter() - started) * 1000)
    record = await record_export(
        db,
        project_id=project_id,
        user_id=user_id,
        export_format=export_format,
        file_name=file_name,
        payload=payload,
        model=model,
        options=options,
        duration_ms=duration,
    )
    return payload, file_name, record


def to_record_response(record: DocumentExport) -> ExportRecordResponse:
    return ExportRecordResponse(
        id=record.id,
        project_id=record.project_id,
        format=record.format,  # type: ignore[arg-type]
        file_name=record.file_name,
        size_bytes=record.size_bytes,
        style=record.style,
        style_label=record.style_label,
        section_count=record.section_count,
        figure_count=record.figure_count,
        table_count=record.table_count,
        citation_count=record.citation_count,
        uncited_count=record.uncited_count,
        orphan_count=record.orphan_count,
        warnings=list(record.warnings or []),
        duration_ms=record.duration_ms,
        created_at=record.created_at or datetime.now(UTC),
    )


async def list_exports(
    db: AsyncSession, *, project_id: UUID, limit: int = 20, offset: int = 0
) -> tuple[list[DocumentExport], int]:
    """The export history of one project, most recent first."""
    total = int(
        (
            await db.execute(
                select(func.count(DocumentExport.id)).where(
                    DocumentExport.project_id == project_id
                )
            )
        ).scalar_one()
    )
    result = await db.execute(
        select(DocumentExport)
        .where(DocumentExport.project_id == project_id)
        .order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def build_preview(
    db: AsyncSession, *, project_id: UUID, options: ExportOptions
) -> dict[str, Any]:
    """What an export would contain, without generating a file.

    Used by the dialog so the author sees the counts and the warnings before waiting for a
    download, and so a broken citation is reported before the file is produced.
    """
    model = await build_document_model(db, project_id=project_id, options=options)
    sections = await load_sections(db, project_id=project_id)
    return {
        "style": model.style,
        "style_label": model.style_label,
        "project_title": model.project_title,
        "section_count": len(sections),
        "section_titles": list(model.section_titles),
        "figure_count": model.figure_count,
        "table_count": model.table_count,
        "citation_count": model.citation_count,
        "bibliography_entries": len(model.bibliography.lines) if model.bibliography else 0,
        "uncited_count": model.uncited_count,
        "orphan_count": model.orphan_count,
        "annex_count": sum(1 for block in model.annexes if block.kind.value == "heading"),
        "warnings": list(model.warnings),
        "has_cover": model.cover is not None,
        "has_toc": any(block.kind.value == "toc" for block in model.blocks),
    }


__all__ = [
    "MAX_NAME_STEM",
    "ExportError",
    "build_file_name",
    "build_preview",
    "generate_export",
    "list_exports",
    "record_export",
    "render_document",
    "to_record_response",
]
