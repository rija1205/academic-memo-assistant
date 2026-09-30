"""Assisted writing HTTP API.

Permissions reuse the project roles: ``owner`` and ``editor`` can generate proposals,
``reader`` cannot. ``reader`` can still consult the generation history of the project.

Security notes:

* a generation is scoped to the project **and** to the authenticated user;
* the ``section_id`` is verified to belong to the project, so a proposal cannot be attached
  to another project's section;
* the API never writes to the thesis. Applying a proposal is an explicit editor action.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.ratelimit import check_assistant_limit, record_assistant_tokens
from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.workspace import Section
from app.projects.access import ProjectAccess, require_project_editor, require_project_reader
from app.writing.actions import action_catalog
from app.writing.pipeline import (
    GenerationProposal,
    generate_proposal,
    generation_citations,
    list_generations,
    store_generation,
)
from app.writing.schemas import (
    WritingActionResponse,
    WritingCatalogResponse,
    WritingCitationResponse,
    WritingGenerationListResponse,
    WritingGenerationSummary,
    WritingRequest,
    WritingResponse,
)

router = APIRouter(prefix="/api/projects", tags=["writing"])


def _validate_inputs(payload: WritingRequest, settings: Settings) -> None:
    if len(payload.selection) > settings.writing_max_selection_chars:
        raise HTTPException(
            status_code=422, detail="La sélection est trop volumineuse."
        )
    if len(payload.section_text) > settings.writing_max_section_chars:
        raise HTTPException(status_code=422, detail="La section est trop volumineuse.")
    if len(payload.instruction) > settings.writing_max_instruction_chars:
        raise HTTPException(status_code=422, detail="L'instruction est trop longue.")


async def _verify_section(
    db: AsyncSession, *, project_id: UUID, section_id: UUID | None
) -> None:
    """Ensure the section belongs to the project before attaching a generation to it."""
    if section_id is None:
        return
    from sqlalchemy import select

    result = await db.execute(
        select(Section.id).where(
            Section.id == section_id, Section.project_id == project_id
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Section not found in this project.")


def _citation_responses(
    proposal: GenerationProposal, project_id: UUID
) -> list[WritingCitationResponse]:
    return [
        WritingCitationResponse(
            position=citation.position,
            citation_id=citation.citation_id,
            chunk_id=citation.chunk_id,
            source_id=citation.source_id,
            source_file_id=citation.source_file_id,
            provenance_id=citation.provenance_id,
            page=citation.page,
            quote=citation.quote,
            rag_score=citation.rag_score,
            source_title=citation.source_title,
            original_filename=citation.original_filename,
            deep_link=(
                f"/projects/{project_id}/sources?source={citation.source_id}&page={citation.page}"
            ),
        )
        for citation in proposal.citations
    ]


@router.get("/{project_id}/writing/actions", response_model=WritingCatalogResponse)
async def get_writing_catalog(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    settings: Settings = Depends(get_settings),
) -> WritingCatalogResponse:
    return WritingCatalogResponse(
        actions=[WritingActionResponse(**item) for item in action_catalog()],
        top_k=settings.writing_top_k,
        max_selection_chars=settings.writing_max_selection_chars,
        max_section_chars=settings.writing_max_section_chars,
    )


@router.post(
    "/{project_id}/writing/generate",
    response_model=WritingResponse,
    summary="Produit une proposition de rédaction (le mémoire n'est jamais modifié)",
)
async def generate(
    project_id: UUID,
    payload: WritingRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> WritingResponse:
    _validate_inputs(payload, settings)
    await _verify_section(db, project_id=project_id, section_id=payload.section_id)
    await check_assistant_limit(
        user_id=current_auth.user.id,
        project_id=project_id,
        text=f"{payload.instruction} {payload.selection}",
        settings=settings,
    )

    try:
        proposal = await generate_proposal(
            db,
            project_id=project_id,
            action=payload.action,
            selection=payload.selection,
            section_text=payload.section_text,
            previous_text=payload.previous_text,
            instruction=payload.instruction,
            settings=settings,
            target_language=payload.target_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    generation = await store_generation(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        section_id=payload.section_id,
        action=payload.action,
        instruction=payload.instruction,
        selection=payload.selection,
        proposal=proposal,
    )
    await record_assistant_tokens(
        user_id=current_auth.user.id,
        project_id=project_id,
        tokens=proposal.total_tokens,
    )

    return WritingResponse(
        generation_id=generation.id,
        action=payload.action,
        status=proposal.status,
        proposed_text=proposal.text,
        user_message=proposal.user_message,
        citations=_citation_responses(proposal, project_id),
        rejected_citations=proposal.rejected_citations,
        grounding_note=proposal.grounding_note,
        used_sources=proposal.used_sources,
        chunks_retrieved=proposal.chunks_retrieved,
        reranked=proposal.reranked,
        llm_provider=proposal.llm_provider,
        llm_model=proposal.llm_model,
        input_tokens=proposal.input_tokens,
        output_tokens=proposal.output_tokens,
        total_tokens=proposal.total_tokens,
        estimated_cost_usd=proposal.cost.cost_usd if proposal.cost else None,
        cost_is_estimate=True,
        rag_duration_ms=proposal.rag_duration_ms,
        llm_duration_ms=proposal.llm_duration_ms,
        error_category=proposal.error_category,
        created_at=generation.created_at,
    )


@router.get(
    "/{project_id}/writing/generations",
    response_model=WritingGenerationListResponse,
)
async def get_generation_history(
    project_id: UUID,
    section_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> WritingGenerationListResponse:
    await _verify_section(db, project_id=project_id, section_id=section_id)
    generations, total = await list_generations(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        section_id=section_id,
        limit=limit,
        offset=offset,
    )
    citations = await generation_citations(db, [item.id for item in generations])
    return WritingGenerationListResponse(
        items=[
            _summary(item, citations.get(item.id, []), project_id) for item in generations
        ],
        total=total,
    )


@router.post(
    "/{project_id}/writing/generations/{generation_id}/discard",
    response_model=WritingGenerationSummary,
    summary="Marque une proposition comme abandonnée",
)
async def discard_generation(
    project_id: UUID,
    generation_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> WritingGenerationSummary:
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.writing import WritingGeneration

    result = await db.execute(
        select(WritingGeneration).where(
            WritingGeneration.id == generation_id,
            WritingGeneration.project_id == project_id,
            WritingGeneration.user_id == current_auth.user.id,
        )
    )
    generation = result.scalar_one_or_none()
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    generation.status = "discarded"
    generation.applied_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(generation)
    citations = await generation_citations(db, [generation.id])
    return _summary(generation, citations.get(generation.id, []), project_id)


def _summary(generation, citations, project_id: UUID) -> WritingGenerationSummary:  # type: ignore[no-untyped-def]
    return WritingGenerationSummary(
        id=generation.id,
        project_id=generation.project_id,
        section_id=generation.section_id,
        action=generation.action,
        status=generation.status,
        instruction=generation.instruction,
        selection_excerpt=generation.selection_excerpt,
        proposed_text=generation.proposed_text,
        llm_provider=generation.llm_provider,
        llm_model=generation.llm_model,
        input_tokens=generation.input_tokens,
        output_tokens=generation.output_tokens,
        total_tokens=generation.total_tokens,
        estimated_cost_usd=generation.estimated_cost_usd,
        cost_is_estimate=generation.cost_is_estimate,
        chunks_retrieved=generation.chunks_retrieved,
        used_sources=generation.used_sources,
        grounding_note=generation.grounding_note,
        error_category=generation.error_category,
        applied_at=generation.applied_at,
        created_at=generation.created_at,
        citations=[
            WritingCitationResponse(
                position=citation.position,
                citation_id=citation.citation_id,
                chunk_id=citation.chunk_id,
                source_id=citation.source_id,
                source_file_id=citation.source_file_id,
                provenance_id=citation.provenance_id,
                page=citation.page,
                quote=citation.quote,
                rag_score=citation.rag_score,
                source_title=citation.source_title,
                original_filename=citation.original_filename,
                deep_link=(
                    f"/projects/{project_id}/sources?source={citation.source_id}"
                    f"&page={citation.page}"
                ),
            )
            for citation in citations
        ],
    )
