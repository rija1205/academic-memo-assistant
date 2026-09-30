"""Export HTTP API.

Permissions follow the roles of the whole application:

* ``reader``: consult the export catalogue, preview an export, read the export history;
* ``editor``: generate a PDF or a DOCX of the memoir;
* ``owner``: everything.

An export is a read of the whole project, but it produces a file, so it is treated as a
mutating action: it requires CSRF and is recorded in the audit trace. Every query is scoped by
``project_id``, so a memoir of another project answers ``404``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.db.session import get_session
from app.export.options import (
    ALIGNMENTS,
    EXPORT_FORMATS,
    MAX_BLOCKS,
    MAX_OUTPUT_BYTES,
    MAX_SECTIONS,
    PAGE_SIZES,
    ExportOptionError,
    build_options,
)
from app.export.orchestrator import (
    ExportError,
    build_preview,
    generate_export,
    list_exports,
    to_record_response,
)
from app.export.schemas import (
    ExportCatalogueResponse,
    ExportFormatInfo,
    ExportListResponse,
    ExportOptionsRequest,
    ExportPreviewRequest,
    ExportPreviewResponse,
    ExportRecordResponse,
)
from app.models.project import Project
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_reader,
)

router = APIRouter(prefix="/api/projects/{project_id}/exports", tags=["exports"])


async def _project_or_404(db: AsyncSession, project_id: UUID) -> Project:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Mémoire introuvable.")
    return project


@router.get("/formats", response_model=ExportCatalogueResponse)
async def formats_endpoint(
    access: ProjectAccess = Depends(require_project_reader),
) -> ExportCatalogueResponse:
    """The formats, page sizes, fonts and defaults, so the dialog hard-codes nothing."""
    defaults = build_options({})
    return ExportCatalogueResponse(
        formats=[
            ExportFormatInfo(
                format=name,  # type: ignore[arg-type]
                label=spec["label"],
                extension=spec["extension"],
                media_type=spec["media_type"],
            )
            for name, spec in EXPORT_FORMATS.items()
        ],
        page_sizes=list(PAGE_SIZES),
        fonts=[
            {"name": "times", "label": "Times New Roman"},
            {"name": "helvetica", "label": "Arial"},
            {"name": "courier", "label": "Courier New"},
        ],
        defaults={
            "page_size": defaults.page_size,
            "orientation": defaults.orientation,
            "font_family": defaults.font_family,
            "font_size": defaults.font_size,
            "line_spacing": defaults.line_spacing,
            "first_line_indent": defaults.first_line_indent,
            "paragraph_alignment": defaults.paragraph_alignment,
            "alignments": sorted(ALIGNMENTS),
            "include_cover": defaults.include_cover,
            "include_toc": defaults.include_toc,
            "include_list_of_figures": defaults.include_list_of_figures,
            "include_list_of_tables": defaults.include_list_of_tables,
            "include_bibliography": defaults.include_bibliography,
            "include_annexes": defaults.include_annexes,
            "include_page_numbers": defaults.include_page_numbers,
            "roman_front_matter": defaults.roman_front_matter,
            "number_headings": defaults.number_headings,
            "embed_remote_images": defaults.embed_remote_images,
            "limits": {
                "max_sections": MAX_SECTIONS,
                "max_blocks": MAX_BLOCKS,
                "max_output_bytes": MAX_OUTPUT_BYTES,
            },
        },
    )


@router.get("", response_model=ExportListResponse)
async def list_exports_endpoint(
    project_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ExportListResponse:
    """The export history of this project only."""
    await _project_or_404(db, project_id)
    records, total = await list_exports(db, project_id=project_id, limit=limit, offset=offset)
    return ExportListResponse(
        items=[to_record_response(record) for record in records], total=total
    )


@router.post("/preview", response_model=ExportPreviewResponse)
async def preview_endpoint(
    project_id: UUID,
    payload: ExportPreviewRequest,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> ExportPreviewResponse:
    """Describe the export without generating it, so warnings surface early."""
    await _project_or_404(db, project_id)
    try:
        options = build_options(payload.options.to_payload())
        preview = await build_preview(db, project_id=project_id, options=options)
    except ExportOptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ExportPreviewResponse(format=payload.format, **preview)  # type: ignore[arg-type]


@router.post("/{export_format}")
async def generate_endpoint(
    project_id: UUID,
    export_format: str,
    options: Annotated[ExportOptionsRequest | None, Body()] = None,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> Response:
    """Generate the memoir as a PDF or a DOCX and stream it back as a download.

    The body is optional so the button works without configuring anything.
    """
    if export_format not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Format d'export non pris en charge : {export_format}.",
        )
    project = await _project_or_404(db, project_id)
    try:
        resolved = build_options(options.to_payload() if options else {})
        payload, file_name, _record = await generate_export(
            db,
            project_id=project_id,
            user_id=current_auth.user.id,
            export_format=export_format,
            options=resolved,
        )
    except ExportOptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    spec = EXPORT_FORMATS[export_format]
    # A quoted filename plus the UTF-8 form, so accented titles survive every browser.
    from urllib.parse import quote

    disposition = (
        f'attachment; filename="{file_name}"; '
        f"filename*=UTF-8''{quote(file_name)}"
    )
    return Response(
        content=payload,
        media_type=spec["media_type"],
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(payload)),
            "X-Export-Project": project.title[:120],
            "Cache-Control": "no-store",
        },
    )


@router.get("/{record_id}", response_model=ExportRecordResponse)
async def get_export_endpoint(
    project_id: UUID,
    record_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ExportRecordResponse:
    """One export record, scoped to this project."""
    from app.models.export import DocumentExport

    await _project_or_404(db, project_id)
    record = (
        await db.execute(
            select(DocumentExport).where(
                DocumentExport.id == record_id,
                DocumentExport.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Export introuvable.")
    return to_record_response(record)
