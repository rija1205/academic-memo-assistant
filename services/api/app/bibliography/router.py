"""Bibliography HTTP API.

Permissions, consistent with the rest of the application:

* ``reader``: read the bibliography, search it, export it, read statistics;
* ``editor``: create, modify, import, merge, delete and link references to sources;
* ``owner``: everything, including deleting references.

Every query is scoped to the project. A reference of another project returns ``404``, never
another project's data, and the same rule applies to a reference id supplied by hand.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

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
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.bibliography.schemas import (
    DuplicateMatchResponse,
    DuplicateReportResponse,
    ImportErrorItem,
    ImportResponse,
    MergeRequest,
    ReferenceCreateRequest,
    ReferenceListResponse,
    ReferenceResponse,
    ReferenceStatsResponse,
    ReferenceUpdateRequest,
)
from app.bibliography.service import (
    create_reference,
    delete_reference,
    duplicates_of,
    get_reference,
    import_parsed,
    list_references,
    merge_references,
    parse_import,
    parsed_objects,
    reference_stats,
    render_export,
    to_response,
    update_reference,
)
from app.citations.schemas import RenderedBibliographyResponse
from app.citations.service import rendered_bibliography
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_owner,
    require_project_reader,
)
from app.sources.validation import UploadValidationError

router = APIRouter(prefix="/api/projects/{project_id}/bibliography", tags=["bibliography"])


@router.get("", response_model=ReferenceListResponse)
async def list_references_endpoint(
    project_id: UUID,
    q: str | None = Query(default=None, max_length=200),
    reference_type: str | None = Query(default=None, max_length=32),
    year: int | None = Query(default=None, ge=1000, le=3000),
    author: str | None = Query(default=None, max_length=200),
    has_doi: bool | None = None,
    has_source: bool | None = None,
    tag: str | None = Query(default=None, max_length=80),
    sort: str = Query(default="updated_at"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ReferenceListResponse:
    references, total = await list_references(
        db,
        project_id=project_id,
        q=q,
        reference_type=reference_type,
        year=year,
        author=author,
        has_doi=has_doi,
        has_source=has_source,
        tag=tag,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return ReferenceListResponse(
        items=[await to_response(db, reference) for reference in references],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=ReferenceStatsResponse)
async def stats_endpoint(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ReferenceStatsResponse:
    raw = await reference_stats(db, project_id=project_id)
    return ReferenceStatsResponse(**raw)  # type: ignore[arg-type]


@router.get("/search", response_model=ReferenceListResponse)
async def search_endpoint(
    project_id: UUID,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ReferenceListResponse:
    """Plain SQL search over title, author, DOI, journal and keywords. No LLM involved."""
    references, total = await list_references(
        db, project_id=project_id, q=q, limit=limit, offset=offset
    )
    return ReferenceListResponse(
        items=[await to_response(db, reference) for reference in references],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export/{export_format}", summary="Exporter la sélection ou toute la bibliothèque")
async def export_endpoint(
    project_id: UUID,
    export_format: str,
    reference_ids: str | None = Query(
        default=None, description="Liste d'ids separes par des virgules"
    ),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> Response:
    if export_format not in {"bibtex", "ris"}:
        raise HTTPException(status_code=400, detail="Format d'export non supporté.")
    if reference_ids:
        try:
            ids = [UUID(value.strip()) for value in reference_ids.split(",") if value.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Identifiant invalide.") from exc
        from sqlalchemy import select

        from app.models.bibliography import BibliographicReference

        references = list(
            (
                await db.execute(
                    select(BibliographicReference).where(
                        BibliographicReference.id.in_(ids),
                        BibliographicReference.project_id == project_id,
                        BibliographicReference.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(references) != len(ids):
            raise HTTPException(status_code=404, detail="Référence introuvable dans ce projet.")
    else:
        references, _ = await list_references(
            db, project_id=project_id, limit=200, offset=0, sort="created_at", order="asc"
        )
    payload = render_export(await parsed_objects(db, references), export_format)
    media_type = (
        "application/x-bibtex"
        if export_format == "bibtex"
        else "application/x-research-info-systems"
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="bibliographie.{export_format}"'
        },
    )


@router.post("/import/{import_format}", response_model=ImportResponse)
async def import_endpoint(
    project_id: UUID,
    import_format: str,
    file: Annotated[UploadFile, File(...)],
    skip_duplicates: bool = Form(default=True),
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> ImportResponse:
    """Import a BibTeX or RIS file.

    The file is treated as untrusted text: it is read with a hard size limit, parsed without
    evaluating anything, and every entry that produces a duplicate is reported rather than
    silently merged.
    """
    if import_format not in {"bibtex", "ris"}:
        raise HTTPException(status_code=400, detail="Format d'import non supporté.")
    data = await file.read(settings.bibliography_max_import_bytes + 1)
    if len(data) > settings.bibliography_max_import_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Fichier trop volumineux : la limite est de "
                f"{settings.bibliography_max_import_bytes} octets."
            ),
        )
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadValidationError(
            "invalid_encoding", "Le fichier doit être encodé en UTF-8."
        ) from exc

    parsed = parse_import(
        content, import_format, max_entries=settings.bibliography_max_import_entries
    )
    created, duplicates, skipped = await import_parsed(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        parsed=list(parsed.references),
        skip_duplicates=skip_duplicates,
    )
    return ImportResponse(
        imported=len(created),
        skipped=skipped + parsed.skipped,
        duplicates=duplicates,
        errors=[ImportErrorItem(message=message) for message in parsed.errors[:100]],
        references=[await to_response(db, reference) for reference in created[:50]],
    )


@router.get("/rendered", response_model=RenderedBibliographyResponse)
async def rendered_bibliography_endpoint(
    project_id: UUID,
    style: str | None = Query(default=None, max_length=64),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> RenderedBibliographyResponse:
    """Render the final bibliography from the references that are actually cited.

    A reference present in the library but never cited is reported as uncited and stays out of
    the bibliography, and a reference cited several times appears exactly once. An
    ``?style=`` override renders a preview of another style without changing the project
    setting.
    """
    payload = await rendered_bibliography(db, project_id=project_id, style_name=style)
    return RenderedBibliographyResponse(**payload)


@router.post("/refresh", response_model=RenderedBibliographyResponse)
async def refresh_bibliography_endpoint(
    project_id: UUID,
    style: str | None = Query(default=None, max_length=64),
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> RenderedBibliographyResponse:
    """Re-render the bibliography after the citations or the references changed.

    The bibliography is derived data, so "refreshing" means recomputing it from the current
    state rather than copying text into the document. The author's own prose is never touched.
    """
    payload = await rendered_bibliography(db, project_id=project_id, style_name=style)
    return RenderedBibliographyResponse(**payload)


@router.post("", response_model=ReferenceResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    project_id: UUID,
    payload: ReferenceCreateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> ReferenceResponse:
    reference = await create_reference(
        db, project_id=project_id, user_id=current_auth.user.id, payload=payload
    )
    return await to_response(db, reference)


@router.get("/{reference_id}", response_model=ReferenceResponse)
async def get_endpoint(
    project_id: UUID,
    reference_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> ReferenceResponse:
    reference = await get_reference(db, project_id=project_id, reference_id=reference_id)
    return await to_response(db, reference)


@router.get("/{reference_id}/duplicates", response_model=DuplicateReportResponse)
async def duplicates_endpoint(
    project_id: UUID,
    reference_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> DuplicateReportResponse:
    reference = await get_reference(db, project_id=project_id, reference_id=reference_id)
    report = await duplicates_of(db, project_id=project_id, reference=reference)
    return DuplicateReportResponse(
        has_duplicates=report.has_matches,
        exact=[
            DuplicateMatchResponse(
                reference_id=match.other_id,
                citation_key=match.other_citation_key,
                title=match.other_title,
                level=match.level,
                reason=match.reason,
                title_similarity=match.title_similarity,
                shared_authors=list(match.shared_authors),
            )
            for match in report.exact
        ],
        strong=[
            DuplicateMatchResponse(
                reference_id=match.other_id,
                citation_key=match.other_citation_key,
                title=match.other_title,
                level=match.level,
                reason=match.reason,
                title_similarity=match.title_similarity,
                shared_authors=list(match.shared_authors),
            )
            for match in report.strong
        ],
        possible=[
            DuplicateMatchResponse(
                reference_id=match.other_id,
                citation_key=match.other_citation_key,
                title=match.other_title,
                level=match.level,
                reason=match.reason,
                title_similarity=match.title_similarity,
                shared_authors=list(match.shared_authors),
            )
            for match in report.possible
        ],
    )


@router.patch("/{reference_id}", response_model=ReferenceResponse)
async def update_endpoint(
    project_id: UUID,
    reference_id: UUID,
    payload: ReferenceUpdateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> ReferenceResponse:
    reference = await get_reference(db, project_id=project_id, reference_id=reference_id)
    updated = await update_reference(
        db, project_id=project_id, reference=reference, payload=payload
    )
    return await to_response(db, updated)


@router.delete("/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    project_id: UUID,
    reference_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    reference = await get_reference(db, project_id=project_id, reference_id=reference_id)
    await delete_reference(db, project_id=project_id, reference=reference)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{reference_id}/merge", response_model=ReferenceResponse)
async def merge_endpoint(
    project_id: UUID,
    reference_id: UUID,
    payload: MergeRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> ReferenceResponse:
    """Merge a duplicate into the reference the author keeps. Nothing is lost."""
    duplicate = await get_reference(db, project_id=project_id, reference_id=reference_id)
    keep = await get_reference(
        db, project_id=project_id, reference_id=payload.keep_reference_id
    )
    if keep.id == duplicate.id:
        raise HTTPException(
            status_code=400,
            detail="Une reference ne peut pas fusionner avec elle-meme.",
        )
    merged = await merge_references(
        db, project_id=project_id, keep=keep, duplicate=duplicate
    )
    return await to_response(db, merged)
