"""Assistant pipeline: question -> RAG retrieval -> context -> LLM -> validated citations.

The retrieval stage is the stage-6 engine, used as-is. The language model never queries the
database: it only receives the passages selected here.

The pipeline is deliberately explicit about its ten steps, because each one is a place where an
academic answer can go wrong:

1. validate the question and the permissions;
2. rate limit and token budget;
3. retrieve passages with the RAG engine (strictly inside the project);
4. rerank when a reranker is configured;
5. stop early with ``insufficient_sources`` when nothing usable was retrieved;
6. build the inert document context with stable citation identifiers;
7. trim the conversation history to a bounded window;
8. call the provider;
9. validate every citation identifier against the passages really sent;
10. persist the answer, the citations, the usage and the timings.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.citations import (
    CitationValidationResult,
    ValidatedCitation,
    render_grounding_note,
    validate_citations,
)
from app.assistant.cost import CostReport, estimate_completion_cost
from app.assistant.llm import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    LlmError,
    LlmMessage,
    LlmProvider,
    build_llm_provider,
    is_context_too_large,
)
from app.assistant.prompts import (
    SYSTEM_PROMPT,
    build_document_context,
    format_user_turn,
    strip_citation_markers,
)
from app.assistant.ratelimit import RateLimitDecision, get_rate_limiter
from app.assistant.schemas import CitationResponse
from app.core.config import Settings
from app.models.assistant import AssistantCitation, AssistantConversation, AssistantMessage
from app.rag.embeddings import EmbeddingError, build_embedding_provider
from app.rag.search.retrieval import ScoredChunk, build_reranker, hybrid_search
from app.rag.settings import rag_tuning

logger = logging.getLogger(__name__)

INSUFFICIENT_SOURCES_MESSAGE = (
    "Les sources disponibles dans ce mémoire ne permettent pas de répondre "
    "suffisamment à cette question."
)
CONTEXT_BUDGET_RATIO = 0.65


@dataclass(slots=True)
class AssistantAnswer:
    """Result of one question, ready to be returned and persisted."""

    status: str
    user_message: str
    answer: str | None = None
    citations: list[ValidatedCitation] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    grounding_note: str | None = None
    chunks_retrieved: int = 0
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

    def citation_responses(self, project_id: UUID) -> list[CitationResponse]:
        return [
            CitationResponse(
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
                authors=list(citation.authors),
                publication_year=citation.publication_year,
                deep_link=(
                    f"/projects/{project_id}/sources?source={citation.source_id}"
                    f"&page={citation.page}"
                ),
            )
            for citation in self.citations
        ]


@dataclass(frozen=True, slots=True)
class HistoryWindow:
    """A bounded slice of the conversation plus an optional summary."""

    messages: tuple[LlmMessage, ...]
    summary: str | None
    trimmed: bool

    @property
    def message_count(self) -> int:
        return len(self.messages)


def validate_question(question: str, settings: Settings) -> str:
    """Reject an empty or oversized question before any work is done."""
    cleaned = question.strip()
    if len(cleaned) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La question doit contenir au moins deux caractères.",
        )
    if len(cleaned) > settings.assistant_max_question_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "La question est trop longue "
                f"({len(cleaned)} caractères, maximum "
                f"{settings.assistant_max_question_length})."
            ),
        )
    return cleaned


async def retrieve_context(
    db: AsyncSession,
    *,
    project_id: UUID,
    question: str,
    settings: Settings,
) -> tuple[list[ScoredChunk], bool, int]:
    """Run the stage-6 retrieval, then rerank when a reranker is configured."""
    tuning = rag_tuning(settings)
    query_embedding: list[float] | None = None
    try:
        provider = build_embedding_provider(settings)
        query_embedding = provider.embed_query(question)
    except EmbeddingError as exc:
        # The hybrid search still works through the lexical path without embeddings.
        logger.info("Embedding indisponible, repli lexical pour l'assistant : %s", exc)
        query_embedding = None

    strategy = "semantic" if query_embedding is not None else "lexical"
    outcome = await hybrid_search(
        db,
        project_id=project_id,
        query=question,
        query_embedding=query_embedding,
        top_k=settings.assistant_top_k,
        tuning=tuning,
        strategy=strategy,
        reranker=build_reranker(settings),
    )
    passages = list(outcome.results)
    reranked = getattr(build_reranker(settings), "name", "none") != "none"
    if settings.assistant_min_context_score > 0:
        passages = [
            chunk for chunk in passages if chunk.score >= settings.assistant_min_context_score
        ]
    return passages, reranked, outcome.duration_ms


def build_history_window(
    *,
    history: list[tuple[str, str]],
    summary: str | None,
    settings: Settings,
    reserved_tokens: int,
) -> HistoryWindow:
    """Keep a bounded window of the conversation inside the prompt budget.

    The oldest complete exchanges are dropped first; the stored rolling summary carries the
    earlier context so the model still understands pronouns such as « et concernant les
    lipides ? ».
    """
    budget = max(
        settings.assistant_max_input_tokens - reserved_tokens,
        settings.assistant_max_input_tokens // 4,
    )
    kept: list[LlmMessage] = []
    used = 0
    trimmed = False
    for role, content in reversed(history):
        message = LlmMessage(role=role, content=content)
        cost = len(content) // 3 + 4
        if used + cost > budget or len(kept) >= settings.assistant_max_history_messages:
            trimmed = True
            break
        kept.append(message)
        used += cost
    kept.reverse()
    return HistoryWindow(messages=tuple(kept), summary=summary, trimmed=trimmed)


async def generate_answer(
    db: AsyncSession,
    *,
    project_id: UUID,
    question: str,
    history: list[tuple[str, str]],
    history_summary: str | None,
    settings: Settings,
    provider: LlmProvider | None = None,
) -> AssistantAnswer:
    """Execute the retrieval-augmented generation for one question."""
    passages, reranked, rag_ms = await retrieve_context(
        db, project_id=project_id, question=question, settings=settings
    )
    if not passages:
        return AssistantAnswer(
            status="insufficient_sources",
            user_message=INSUFFICIENT_SOURCES_MESSAGE,
            chunks_retrieved=0,
            reranked=reranked,
            rag_duration_ms=rag_ms,
            llm_provider=provider.name if provider else None,
            llm_model=provider.model if provider else None,
        )

    document_context, context_passages = build_document_context(passages)
    user_turn = format_user_turn(
        question=question,
        document_context=document_context,
        history_summary=history_summary,
    )
    window = build_history_window(
        history=history,
        summary=history_summary,
        settings=settings,
        reserved_tokens=len(user_turn) + len(SYSTEM_PROMPT),
    )
    messages = [
        LlmMessage(role=ROLE_SYSTEM, content=SYSTEM_PROMPT),
        *window.messages,
        LlmMessage(role=ROLE_USER, content=user_turn),
    ]
    if is_context_too_large(messages, settings):
        # Keep the question and the system rules, drop the history first.
        messages = [
            LlmMessage(role=ROLE_SYSTEM, content=SYSTEM_PROMPT),
            LlmMessage(role=ROLE_USER, content=user_turn),
        ]

    llm_started = time.perf_counter()
    llm_provider = provider or build_llm_provider(settings)
    try:
        completion = llm_provider.complete(messages=messages)
    except LlmError as exc:
        llm_ms = int((time.perf_counter() - llm_started) * 1000)
        logger.warning("Assistant LLM en echec (%s) : %s", exc.category, exc)
        return AssistantAnswer(
            status="failed",
            user_message=exc.user_message,
            chunks_retrieved=len(passages),
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
    readable = strip_citation_markers(completion.content)
    grounding_note = render_grounding_note(
        result=validation, insufficient_sources=False
    )
    cost = estimate_completion_cost(completion, settings)
    return AssistantAnswer(
        status="completed",
        user_message=readable.strip(),
        answer=readable.strip(),
        citations=validation.accepted,
        rejected=[item.citation_id for item in validation.rejected],
        grounding_note=grounding_note,
        chunks_retrieved=len(passages),
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


# ------------------------------------------------------------------- persistence


async def create_conversation(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    title: str | None,
) -> AssistantConversation:
    conversation = AssistantConversation(
        project_id=project_id,
        user_id=user_id,
        title=(title or "Nouvelle conversation").strip()[:300] or "Nouvelle conversation",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(
    db: AsyncSession,
    *,
    project_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
) -> AssistantConversation:
    """Fetch a conversation, enforcing both the project and the owner.

    A conversation of another user is reported as not found: the API must not reveal that it
    exists.
    """
    result = await db.execute(
        select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.project_id == project_id,
            AssistantConversation.user_id == user_id,
            AssistantConversation.deleted_at.is_(None),
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


async def next_sequence(db: AsyncSession, conversation_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(AssistantMessage.sequence), 0) + 1).where(
            AssistantMessage.conversation_id == conversation_id
        )
    )
    return int(result.scalar_one())


async def conversation_history(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    limit: int,
) -> list[tuple[str, str]]:
    """Return the last exchanges, excluding failed and empty answers."""
    result = await db.execute(
        select(AssistantMessage.role, AssistantMessage.content)
        .where(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role.in_([ROLE_USER, ROLE_ASSISTANT]),
            AssistantMessage.status.in_(["completed", "insufficient_sources"]),
        )
        .order_by(AssistantMessage.sequence.desc())
        .limit(limit)
    )
    rows = list(result.all())
    rows.reverse()
    return [(role, content) for role, content in rows]


async def store_exchange(
    db: AsyncSession,
    *,
    conversation: AssistantConversation,
    question: str,
    answer: AssistantAnswer,
) -> tuple[AssistantMessage, AssistantMessage]:
    """Persist the question, the answer and the validated citations."""
    user_sequence = await next_sequence(db, conversation.id)
    now = datetime.now(UTC)
    user_message = AssistantMessage(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        role=ROLE_USER,
        content=question,
        status="completed",
        sequence=user_sequence,
    )
    db.add(user_message)
    await db.flush()

    assistant_message = AssistantMessage(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        role=ROLE_ASSISTANT,
        content=answer.user_message,
        status=answer.status,
        sequence=user_sequence + 1,
        llm_provider=answer.llm_provider,
        llm_model=answer.llm_model,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        total_tokens=answer.total_tokens,
        estimated_cost_usd=(answer.cost.cost_usd if answer.cost else 0.0) or 0.0,
        cost_is_estimate=True,
        rag_duration_ms=answer.rag_duration_ms,
        llm_duration_ms=answer.llm_duration_ms,
        chunks_retrieved=answer.chunks_retrieved,
        error_category=answer.error_category,
        grounding_note=answer.grounding_note,
        metadata_json={
            "rejected_citations": answer.rejected,
            "reranked": answer.reranked,
            "cost_reason": answer.cost.reason if answer.cost else None,
        },
        created_at=now,
    )
    db.add(assistant_message)
    await db.flush()

    for citation in answer.citations:
        db.add(
            AssistantCitation(
                message_id=assistant_message.id,
                conversation_id=conversation.id,
                project_id=conversation.project_id,
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

    conversation.message_count += 2
    conversation.updated_at = now
    await db.commit()
    await db.refresh(assistant_message)
    return user_message, assistant_message


async def message_citations(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[AssistantCitation]]:
    if not message_ids:
        return {}
    result = await db.execute(
        select(AssistantCitation)
        .where(AssistantCitation.message_id.in_(message_ids))
        .order_by(AssistantCitation.position.asc())
    )
    grouped: dict[UUID, list[AssistantCitation]] = {}
    for citation in result.scalars().all():
        grouped.setdefault(citation.message_id, []).append(citation)
    return grouped


async def conversation_messages(
    db: AsyncSession, conversation_id: UUID
) -> list[AssistantMessage]:
    result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.sequence.asc())
    )
    return list(result.scalars().all())


async def list_conversations(
    db: AsyncSession, *, project_id: UUID, user_id: UUID, limit: int, offset: int
) -> tuple[list[AssistantConversation], int]:
    conditions = (
        AssistantConversation.project_id == project_id,
        AssistantConversation.user_id == user_id,
        AssistantConversation.deleted_at.is_(None),
    )
    total = int(
        (
            await db.execute(
                select(func.count(AssistantConversation.id)).where(*conditions)
            )
        ).scalar_one()
    )
    result = await db.execute(
        select(AssistantConversation)
        .where(*conditions)
        .order_by(AssistantConversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def delete_conversation(db: AsyncSession, conversation: AssistantConversation) -> None:
    """Soft delete the conversation and drop its rows to respect the deletion policy."""
    await db.execute(
        delete(AssistantCitation).where(
            AssistantCitation.conversation_id == conversation.id
        )
    )
    await db.execute(
        delete(AssistantMessage).where(AssistantMessage.conversation_id == conversation.id)
    )
    conversation.deleted_at = datetime.now(UTC)
    await db.commit()


async def check_rate_limit(
    *,
    user_id: UUID,
    project_id: UUID,
    question: str,
    settings: Settings,
) -> RateLimitDecision:
    decision = await get_rate_limiter().check(
        user_id=user_id, project_id=project_id, estimated_tokens=len(question) // 3
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=decision.reason or "Limite d'utilisation atteinte.",
            headers={"Retry-After": str(decision.retry_after_seconds or 60)},
        )
    return decision


async def record_usage(
    *, user_id: UUID, project_id: UUID, answer: AssistantAnswer
) -> None:
    if answer.total_tokens > 0:
        await get_rate_limiter().record_tokens(
            user_id=user_id, project_id=project_id, tokens=answer.total_tokens
        )


def new_message_id() -> UUID:
    return uuid4()
