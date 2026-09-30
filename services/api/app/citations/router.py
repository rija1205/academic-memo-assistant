"""Citation HTTP API.

Permissions follow the roles already used by the rest of the application:

* ``reader``: list, read, render the section and the bibliography;
* ``editor``: create, update, delete, reconcile a document, refresh the bibliography;
* ``owner``: everything.

Every statement is scoped by ``project_id``. A citation, a reference or a section belonging to
another project answers ``404``, never a hint that it exists, which is the same rule the other
stages use.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.citations.data import CitationData, CitationItemData
from app.citations.schemas import (
    CitationCreateRequest,
    CitationListResponse,
    CitationResponse,
    CitationUpdateRequest,
    DocumentCitationCheckResponse,
    PreviewRequest,
    PreviewResponse,
    SectionRenderResponse,
    StyleCatalogueEntry,
)
from app.citations.service import (
    get_citation,
    load_reference_data,
    orphaned_citations,
    reconcile_section,
    render_citations,
    resolve_project_style,
    soft_delete_citation,
    update_citation,
    upsert_citation,
)
from app.citations.styles import available_styles, get_style
from app.db.session import get_session
from app.projects.access import (
    ProjectAccess,
    require_project_editor,
    require_project_owner,
    require_project_reader,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/citations", tags=["citations"]
)


@router.get("/styles", response_model=list[StyleCatalogueEntry])
async def styles_endpoint(
    access: ProjectAccess = Depends(require_project_reader),
) -> list[StyleCatalogueEntry]:
    """The catalogue of available styles, so the interface never hard-codes a list."""
    return [StyleCatalogueEntry(**entry) for entry in available_styles()]


@router.get("", response_model=CitationListResponse)
async def list_citations_endpoint(
    project_id: UUID,
    section_id: UUID | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> CitationListResponse:
    rendered, _ = await render_citations(
        db, project_id=project_id, section_id=section_id
    )
    return CitationListResponse(
        items=[
            CitationResponse(
                **await _to_response_fields(
                    db, project_id=project_id, citation=citation, rendered=item
                )
            )
            for citation, item in rendered
        ],
        total=len(rendered),
    )


async def _to_response_fields(
    db: AsyncSession, *, project_id: UUID, citation: Any, rendered: Any
) -> dict[str, Any]:
    """Build the API view of a citation, including the freshness of its snapshot."""
    from app.citations.service import _is_orphaned, _items_by_citation

    items = await _items_by_citation(db, [citation.id])
    rows = items.get(citation.id, [])
    references = await load_reference_data(db, [row.reference_id for row in rows])
    return {
        "id": citation.id,
        "project_id": citation.project_id,
        "section_id": citation.section_id,
        "node_id": citation.node_id,
        "citation_key": citation.citation_key,
        "prefix": citation.prefix,
        "suffix": citation.suffix,
        "locator_type": citation.locator_type,
        "locator_value": citation.locator_value,
        "mode": citation.mode,
        "position_in_section": citation.position_in_section,
        "items": [
            {
                "reference_id": row.reference_id,
                "citation_key": references[row.reference_id].citation_key
                if row.reference_id in references
                else None,
                "title": references[row.reference_id].title
                if row.reference_id in references
                else None,
                "publication_year": references[row.reference_id].publication_year
                if row.reference_id in references
                else None,
                "author_labels": [
                    author.display
                    for author in references[row.reference_id].authors
                ]
                if row.reference_id in references
                else [],
                "position": row.position,
                "locator_type": row.locator_type or citation.locator_type,
                "locator_value": row.locator_value or citation.locator_value,
                "prefix": row.prefix,
                "suffix": row.suffix,
                "is_available": row.reference_id in references,
                "number": None,
            }
            for row in rows
        ],
        "rendered_text": rendered.text,
        "warnings": rendered.warnings,
        "is_orphaned": _is_orphaned(rows, references) or rendered.is_orphaned,
        "is_complete": not rendered.warnings and not rendered.is_orphaned,
        # The display is derived from live metadata, so a snapshot that no longer matches is
        # a signal, not an error: it is exactly what "synchronised" means here.
        "is_stale_snapshot": bool(
            citation.snapshot_text and citation.snapshot_text != rendered.text
        ),
        "snapshot_text": citation.snapshot_text,
        "created_at": citation.created_at.isoformat() if citation.created_at else "",
        "updated_at": citation.updated_at.isoformat() if citation.updated_at else "",
    }


@router.get("/rendered", response_model=SectionRenderResponse)
async def rendered_endpoint(
    project_id: UUID,
    section_id: UUID | None = Query(default=None),
    style: str | None = Query(default=None, max_length=64),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> SectionRenderResponse:
    """Return the text every citation must display, computed by the style engine.

    The editor uses this as its single source of truth for citation text, so the preview shown
    while choosing a reference and the final document can never disagree.
    """
    rendered, style_value = await render_citations(
        db, project_id=project_id, section_id=section_id, style_name=style
    )
    orphans = await orphaned_citations(db, project_id=project_id)
    orphan_nodes = [item["node_id"] for item in orphans]
    return SectionRenderResponse(
        section_id=section_id or UUID(int=0),
        style=style_value,
        style_label=get_style(style_value).label,
        citations=[item for _, item in rendered],
        orphaned=orphan_nodes,
    )


@router.post("/preview", response_model=PreviewResponse)
async def preview_endpoint(
    project_id: UUID,
    payload: PreviewRequest,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> PreviewResponse:
    """Render a citation that is not stored yet, with the very same engine.

    Used by the picker so the author sees ``(Dupont, 2024, p. 25)`` before inserting anything.
    The preview writes nothing, but it is a POST like every other state-changing verb in this
    router, so it carries the CSRF requirement too rather than relying on a subtle distinction.
    """
    style_value = await resolve_project_style(db, project_id=project_id, override=payload.style)
    style = get_style(style_value)
    references = await load_reference_data(
        db, [item.reference_id for item in payload.items]
    )
    missing = [
        str(item.reference_id)
        for item in payload.items
        if item.reference_id not in references
    ]
    if missing:
        # Never fabricate a preview from a reference the caller cannot see.
        raise HTTPException(status_code=404, detail="Référence introuvable dans ce projet.")
    engine_items = tuple(
        CitationItemData(
            reference=references[item.reference_id],
            position=position,
            locator_type=item.locator_type,
            locator_value=item.locator_value,
            prefix=item.prefix,
            suffix=item.suffix,
        )
        for position, item in enumerate(payload.items, start=1)
    )
    engine = CitationData(
        citation_id="preview",
        items=engine_items,
        prefix=payload.prefix,
        suffix=payload.suffix,
        mode=payload.mode,
    )
    rendered = style.format_citation(engine)
    warnings = list(rendered.warnings)
    entry = style.format_bibliography_entry(engine_items[0].reference)
    warnings.extend(entry.warnings)
    return PreviewResponse(
        style=style_value,
        style_label=style.label,
        citation=rendered.text,
        bibliography_entry=entry.text,
        warnings=warnings,
    )


@router.post("/reconcile", response_model=DocumentCitationCheckResponse)
async def reconcile_endpoint(
    project_id: UUID,
    section_id: UUID,
    content: Annotated[dict[str, Any], Body()],
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> DocumentCitationCheckResponse:
    """Register the citations of a saved document and report what needs repair.

    Called after an autosave. Idempotent: a node that is already registered is updated, not
    duplicated.
    """
    return await reconcile_section(
        db,
        project_id=project_id,
        section_id=section_id,
        user_id=current_auth.user.id,
        content=content,
    )


@router.post("", response_model=CitationResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    project_id: UUID,
    payload: CitationCreateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> CitationResponse:
    citation = await upsert_citation(
        db, project_id=project_id, user_id=current_auth.user.id, payload=payload
    )
    rendered = await render_citations(
        db, project_id=project_id, section_id=citation.section_id
    )
    for candidate, item in rendered:
        if candidate.id == citation.id:
            return CitationResponse(
                **await _to_response_fields(
                    db, project_id=project_id, citation=citation, rendered=item
                )
            )
    raise HTTPException(status_code=500, detail="Citation introuvable après création.")


@router.get("/{citation_id}", response_model=CitationResponse)
async def get_endpoint(
    project_id: UUID,
    citation_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
) -> CitationResponse:
    citation = await get_citation(db, project_id=project_id, citation_id=citation_id)
    rendered, _ = await render_citations(
        db, project_id=project_id, section_id=citation.section_id
    )
    for candidate, item in rendered:
        if candidate.id == citation.id:
            return CitationResponse(
                **await _to_response_fields(
                    db, project_id=project_id, citation=citation, rendered=item
                )
            )
    raise HTTPException(status_code=404, detail="Citation introuvable.")


@router.patch("/{citation_id}", response_model=CitationResponse)
async def update_endpoint(
    project_id: UUID,
    citation_id: UUID,
    payload: CitationUpdateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> CitationResponse:
    citation = await get_citation(db, project_id=project_id, citation_id=citation_id)
    updated = await update_citation(
        db, project_id=project_id, citation=citation, payload=payload
    )
    rendered, _ = await render_citations(
        db, project_id=project_id, section_id=updated.section_id
    )
    for candidate, item in rendered:
        if candidate.id == updated.id:
            return CitationResponse(
                **await _to_response_fields(
                    db, project_id=project_id, citation=updated, rendered=item
                )
            )
    raise HTTPException(status_code=404, detail="Citation introuvable.")


@router.delete("/{citation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    project_id: UUID,
    citation_id: UUID,
    access: ProjectAccess = Depends(require_project_owner),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> Response:
    """Delete the citation. The bibliographic reference itself is never touched."""
    citation = await get_citation(db, project_id=project_id, citation_id=citation_id)
    await soft_delete_citation(db, project_id=project_id, citation=citation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{citation_id}/detach-reference", response_model=CitationResponse)
async def detach_reference_endpoint(
    project_id: UUID,
    citation_id: UUID,
    reference_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    _: None = Depends(require_csrf),
) -> CitationResponse:
    """Remove one reference from a citation, used to repair an orphan."""
    citation = await get_citation(db, project_id=project_id, citation_id=citation_id)
    updated = await update_citation(
        db,
        project_id=project_id,
        citation=citation,
        payload=CitationUpdateRequest(remove_reference_id=reference_id),
    )
    rendered, _ = await render_citations(
        db, project_id=project_id, section_id=updated.section_id
    )
    for candidate, item in rendered:
        if candidate.id == updated.id:
            return CitationResponse(
                **await _to_response_fields(
                    db, project_id=project_id, citation=updated, rendered=item
                )
            )
    raise HTTPException(status_code=404, detail="Citation introuvable.")
