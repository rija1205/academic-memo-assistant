"""Writing assistant pipeline.

The single invariant of this module: **the backend never writes to the thesis.** A generation
returns a proposal; applying it is an explicit user action performed in the editor through
the existing section-save endpoint, with the normal optimistic concurrency control. Nothing
here touches ``sections`` or ``section_revisions``.

Flow for one generation:

1. resolve the action and validate the inputs (selection, section, instruction);
2. rate limit and token budget, reusing the stage-7 limiter;
3. for source-backed actions, retrieve passages with the stage-6 RAG engine inside the
   project, then rerank;
4. build the inert document context with stable ``SRC-xxx`` identifiers;
5. call the LLM provider;
6. validate every citation identifier against the passages really sent;
7. persist the generation with its provenance, citations, cost and model.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.citations import (
    CitationValidationResult,
    ValidatedCitation,
    render_grounding_note,
    validate_citations,
)
from app.assistant.cost import CostReport, estimate_completion_cost
from app.assistant.llm import (
    ROLE_SYSTEM,
    ROLE_USER,
    LlmError,
    LlmMessage,
    LlmProvider,
    build_llm_provider,
)
from app.assistant.prompts import (
    build_document_context,
    strip_citation_markers,
)
from app.writing.actions import ActionSpec, WritingAction, get_spec, system_prompt

logger = logging.getLogger(__name__)

SELECTION_PLACEHOLDER = "(selection de l'auteur)"

INSUFFICIENT_SOURCES_MESSAGE = (
    "Les sources indexées de ce mémoire ne permettent pas de traiter cette demande. "
    "Ajoutez des sources ou reformulez votre besoin."
)


@dataclass(slots=True)
class GenerationProposal:
    """What the model proposed. The editor decides whether to apply it."""

    action: WritingAction
    text: str
    status: str
    user_message: str
    citations: list[ValidatedCitation] = field(default_factory=list)
    rejected_citations: list[str] = field(default_factory=list)
    grounding_note: str | None = None
    chunks_retrieved: int = 0
    used_sources: bool = False
    reranked: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: CostReport | None = None
    rag_duration_ms: int = 0
    llm_duration_ms: int = 0
    error_category: str | None = None


def _clean(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def build_user_turn(
    spec: ActionSpec,
    *,
    instruction: str,
    selection: str,
    section_text: str,
    previous_text: str,
    target_language: str | None = None,
) -> str:
    """Assemble the user turn: instructions, author text, then the document data.

    The author text comes before the untrusted documents, so the documents are the last thing
    the model reads before generating.
    """
    parts: list[str] = []
    author_instruction = _clean(instruction)
    if author_instruction:
        parts.extend(["<author_instruction>", author_instruction, "</author_instruction>"])

    if spec.needs_full_section:
        parts.extend(
            [
                "<section_to_analyse>",
                _clean(section_text) or "(section vide)",
                "</section_to_analyse>",
            ]
        )
    else:
        if previous_text:
            parts.extend(
                [
                    "<previous_text>",
                    _clean(previous_text),
                    "</previous_text>",
                ]
            )
        if selection:
            parts.extend(
                [
                    "<author_selection>",
                    _clean(selection),
                    "</author_selection>",
                ]
            )

    if target_language:
        parts.extend([f"<output_language>{target_language}</output_language>"])
    return "\n".join(parts)


def attach_document_context(user_turn: str, document_context: str) -> str:
    """Append the inert document block after the author text."""
    from app.assistant.prompts import DOCUMENT_CONTEXT_GUIDE

    return (
        f"{user_turn}\n\n"
        f"{DOCUMENT_CONTEXT_GUIDE}\n"
        f"<document_context>\n{document_context.strip() or '(aucun passage disponible)'}\n"
        f"</document_context>"
    )


async def generate_proposal(
    db: AsyncSession,
    *,
    project_id: UUID,
    action: WritingAction,
    selection: str,
    section_text: str,
    previous_text: str,
    instruction: str,
    settings,
    provider: LlmProvider | None = None,
    target_language: str | None = None,
) -> GenerationProposal:
    """Run one writing action and return a proposal. Nothing is written to the thesis."""
    spec = get_spec(action)
    selection = _clean(selection)
    section_text = _clean(section_text)
    instruction = _clean(instruction)

    if spec.needs_selection and not selection and not spec.needs_full_section:
        raise ValueError("Sélectionnez un passage avant de lancer cette action.")
    if spec.needs_full_section and not section_text:
        raise ValueError("La section est vide : rien à analyser.")

    llm_provider = provider or build_llm_provider(settings)
    passages = []
    reranked = False
    rag_ms = 0
    if spec.uses_sources:
        passages, reranked, rag_ms = await _retrieve(
            db,
            project_id=project_id,
            query=_retrieval_query(action, instruction, selection, section_text),
            settings=settings,
        )
        if not passages:
            return GenerationProposal(
                action=action,
                text="",
                status="insufficient_sources",
                user_message=INSUFFICIENT_SOURCES_MESSAGE,
                llm_provider=llm_provider.name,
                llm_model=llm_provider.model,
                rag_duration_ms=rag_ms,
            )

    document_context, context_passages = (
        build_document_context(passages) if spec.uses_sources else ("", [])
    )
    user_turn = build_user_turn(
        spec,
        instruction=instruction,
        selection=selection,
        section_text=section_text,
        previous_text=previous_text,
        target_language=target_language,
    )
    if spec.uses_sources:
        user_turn = attach_document_context(user_turn, document_context)

    messages = [
        LlmMessage(role=ROLE_SYSTEM, content=system_prompt(action)),
        LlmMessage(role=ROLE_USER, content=user_turn),
    ]

    llm_started = time.perf_counter()
    try:
        completion = llm_provider.complete(messages=messages)
    except LlmError as exc:
        llm_ms = int((time.perf_counter() - llm_started) * 1000)
        logger.warning("Echec de generation (%s) action=%s : %s", exc.category, action, exc)
        return GenerationProposal(
            action=action,
            text="",
            status="failed",
            user_message=exc.user_message,
            chunks_retrieved=len(passages),
            used_sources=spec.uses_sources,
            reranked=reranked,
            rag_duration_ms=rag_ms,
            llm_duration_ms=llm_ms,
            llm_provider=llm_provider.name,
            llm_model=llm_provider.model,
            error_category=exc.category,
        )
    llm_ms = int((time.perf_counter() - llm_started) * 1000)

    validation: CitationValidationResult = validate_citations(
        answer=completion.content,
        passages=context_passages,
        project_id=project_id,
    )
    readable = _clean(strip_citation_markers(completion.content))
    cost = estimate_completion_cost(completion, settings)
    return GenerationProposal(
        action=action,
        text=readable,
        status="completed",
        user_message=readable,
        citations=validation.accepted,
        rejected_citations=[item.citation_id for item in validation.rejected],
        grounding_note=render_grounding_note(
            result=validation, insufficient_sources=False
        ),
        chunks_retrieved=len(passages),
        used_sources=spec.uses_sources,
        reranked=reranked,
        rag_duration_ms=rag_ms,
        llm_duration_ms=llm_ms,
        llm_provider=completion.provider,
        llm_model=completion.model,
        input_tokens=completion.usage.input_tokens,
        output_tokens=completion.usage.output_tokens,
        total_tokens=completion.usage.total_tokens,
        cost=cost,
    )


def _retrieval_query(
    action: WritingAction, instruction: str, selection: str, section_text: str
) -> str:
    """Build the retrieval query: the instruction first, then the author text."""
    parts = [instruction, selection or section_text]
    return " ".join(part for part in parts if part).strip()


async def _retrieve(
    db: AsyncSession, *, project_id: UUID, query: str, settings
) -> tuple[list, bool, int]:
    """Retrieve passages with the stage-6 engine, strictly inside the project."""
    from app.rag.embeddings import EmbeddingError, build_embedding_provider
    from app.rag.search.retrieval import build_reranker, hybrid_search
    from app.rag.settings import rag_tuning

    query_embedding: list[float] | None = None
    try:
        query_embedding = build_embedding_provider(settings).embed_query(query)
    except EmbeddingError as exc:
        logger.info("Embedding indisponible pour la redaction, repli lexical : %s", exc)

    reranker = build_reranker(settings)
    outcome = await hybrid_search(
        db,
        project_id=project_id,
        query=query,
        query_embedding=query_embedding,
        top_k=getattr(settings, "writing_top_k", 8),
        tuning=rag_tuning(settings),
        strategy="semantic" if query_embedding is not None else "lexical",
        reranker=reranker,
    )
    return (
        list(outcome.results),
        getattr(reranker, "name", "none") != "none",
        outcome.duration_ms,
    )


# ------------------------------------------------------------------- persistence


async def store_generation(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    section_id: UUID | None,
    action: WritingAction,
    instruction: str,
    selection: str,
    proposal: GenerationProposal,
) -> object:
    """Persist one generation so the author can review the history later."""
    from app.models.writing import WritingCitation, WritingGeneration

    now = datetime.now(UTC)
    generation = WritingGeneration(
        project_id=project_id,
        user_id=user_id,
        section_id=section_id,
        action=action.value,
        instruction=_clean(instruction)[:2000],
        selection_excerpt=_clean(selection)[:2000],
        proposed_text=proposal.text,
        status=proposal.status,
        llm_provider=proposal.llm_provider,
        llm_model=proposal.llm_model,
        input_tokens=proposal.input_tokens,
        output_tokens=proposal.output_tokens,
        total_tokens=proposal.total_tokens,
        estimated_cost_usd=(proposal.cost.cost_usd if proposal.cost else 0.0) or 0.0,
        cost_is_estimate=True,
        chunks_retrieved=proposal.chunks_retrieved,
        used_sources=proposal.used_sources,
        rejected_citations=proposal.rejected_citations,
        grounding_note=proposal.grounding_note,
        error_category=proposal.error_category,
        rag_duration_ms=proposal.rag_duration_ms,
        llm_duration_ms=proposal.llm_duration_ms,
        created_at=now,
    )
    db.add(generation)
    await db.flush()
    for citation in proposal.citations:
        db.add(
            WritingCitation(
                generation_id=generation.id,
                project_id=project_id,
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
            )
        )
    await db.commit()
    await db.refresh(generation)
    return generation


async def list_generations(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    section_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list, int]:
    from app.models.writing import WritingGeneration

    conditions = [
        WritingGeneration.project_id == project_id,
        WritingGeneration.user_id == user_id,
    ]
    if section_id is not None:
        conditions.append(WritingGeneration.section_id == section_id)
    total = int(
        (
            await db.execute(select(func.count(WritingGeneration.id)).where(*conditions))
        ).scalar_one()
    )
    result = await db.execute(
        select(WritingGeneration)
        .where(*conditions)
        .order_by(WritingGeneration.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def generation_citations(db: AsyncSession, generation_ids: list[UUID]) -> dict[UUID, list]:
    from app.models.writing import WritingCitation

    if not generation_ids:
        return {}
    result = await db.execute(
        select(WritingCitation)
        .where(WritingCitation.generation_id.in_(generation_ids))
        .order_by(WritingCitation.position.asc())
    )
    grouped: dict[UUID, list] = {}
    for citation in result.scalars().all():
        grouped.setdefault(citation.generation_id, []).append(citation)
    return grouped
