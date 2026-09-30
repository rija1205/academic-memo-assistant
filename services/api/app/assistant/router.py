"""Assistant HTTP API.

Permissions follow the existing project roles:

* ``owner`` and ``editor``: full access, including asking questions and managing conversations.
* ``reader``: read-only access to the sources. Asking a question triggers a paid generation,
  so it is restricted to ``editor`` and ``owner``.

Every conversation lookup is additionally scoped to the authenticated user, so a conversation
of another user is reported as not found even inside the same project.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.pipeline import (
    check_rate_limit,
    conversation_history,
    conversation_messages,
    create_conversation,
    delete_conversation,
    generate_answer,
    get_conversation,
    list_conversations,
    message_citations,
    record_usage,
    store_exchange,
    validate_question,
)
from app.assistant.ratelimit import get_rate_limiter
from app.assistant.schemas import (
    AskRequest,
    AskResponse,
    AssistantConfigResponse,
    AssistantUsageResponse,
    CitationResponse,
    ConversationCreateRequest,
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    MessageResponse,
)
from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.projects.access import ProjectAccess, require_project_editor, require_project_reader

router = APIRouter(prefix="/api", tags=["assistant"])

@router.post(
    "/projects/{project_id}/assistant/conversations",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_conversation(
    project_id: UUID,
    payload: ConversationCreateRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> ConversationDetailResponse:
    conversation = await create_conversation(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        title=payload.title,
    )
    return ConversationDetailResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        summary=conversation.summary,
        messages=[],
    )


@router.get(
    "/projects/{project_id}/assistant/conversations",
    response_model=ConversationListResponse,
)
async def get_conversations(
    project_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> ConversationListResponse:
    conversations, total = await list_conversations(
        db,
        project_id=project_id,
        user_id=current_auth.user.id,
        limit=limit,
        offset=offset,
    )
    return ConversationListResponse(
        items=[
            ConversationSummaryResponse(
                id=conversation.id,
                project_id=conversation.project_id,
                title=conversation.title,
                message_count=conversation.message_count,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            for conversation in conversations
        ],
        total=total,
    )


@router.get(
    "/projects/{project_id}/assistant/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation_detail(
    project_id: UUID,
    conversation_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> ConversationDetailResponse:
    conversation = await get_conversation(
        db,
        project_id=project_id,
        conversation_id=conversation_id,
        user_id=current_auth.user.id,
    )
    messages = await conversation_messages(db, conversation.id)
    citations = await message_citations(db, [message.id for message in messages])
    return ConversationDetailResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        summary=conversation.summary,
        messages=[
            _message_response(message, citations.get(message.id, []), project_id)
            for message in messages
        ],
    )


@router.delete(
    "/projects/{project_id}/assistant/conversations/{conversation_id}",
    response_model=ConversationDeleteResponse,
)
async def remove_conversation(
    project_id: UUID,
    conversation_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> ConversationDeleteResponse:
    conversation = await get_conversation(
        db,
        project_id=project_id,
        conversation_id=conversation_id,
        user_id=current_auth.user.id,
    )
    await delete_conversation(db, conversation)
    return ConversationDeleteResponse(
        message="Conversation supprimée.", conversation_id=conversation.id
    )


@router.post(
    "/projects/{project_id}/assistant/ask",
    response_model=AskResponse,
    summary="Pose une question et obtient une réponse fondée sur les sources du projet",
)
async def ask_question(
    project_id: UUID,
    payload: AskRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> AskResponse:
    question = validate_question(payload.question, settings)
    await check_rate_limit(
        user_id=current_auth.user.id,
        project_id=project_id,
        question=question,
        settings=settings,
    )

    if payload.conversation_id is not None:
        conversation = await get_conversation(
            db,
            project_id=project_id,
            conversation_id=payload.conversation_id,
            user_id=current_auth.user.id,
        )
    else:
        conversation = await create_conversation(
            db,
            project_id=project_id,
            user_id=current_auth.user.id,
            title=question[:120],
        )

    history = await conversation_history(
        db,
        conversation_id=conversation.id,
        limit=settings.assistant_max_history_messages,
    )
    answer = await generate_answer(
        db,
        project_id=project_id,
        question=question,
        history=history,
        history_summary=conversation.summary,
        settings=settings,
    )
    _, assistant_message = await store_exchange(
        db, conversation=conversation, question=question, answer=answer
    )
    await record_usage(
        user_id=current_auth.user.id, project_id=project_id, answer=answer
    )
    return AskResponse(
        status=answer.status,
        message_id=assistant_message.id,
        conversation_id=conversation.id,
        question=question,
        answer=answer.answer,
        user_message=answer.user_message,
        citations=answer.citation_responses(project_id),
        rejected_citations=answer.rejected,
        grounding_note=answer.grounding_note,
        chunks_retrieved=answer.chunks_retrieved,
        reranked=answer.reranked,
        llm_provider=answer.llm_provider,
        llm_model=answer.llm_model,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        total_tokens=answer.total_tokens,
        estimated_cost_usd=answer.cost.cost_usd if answer.cost else None,
        cost_is_estimate=True,
        rag_duration_ms=answer.rag_duration_ms,
        llm_duration_ms=answer.llm_duration_ms,
        created_at=assistant_message.created_at,
    )


@router.post(
    "/projects/{project_id}/assistant/conversations/{conversation_id}/messages",
    response_model=AskResponse,
    summary="Poursuit une conversation existante",
)
async def post_message(
    project_id: UUID,
    conversation_id: UUID,
    payload: AskRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> AskResponse:
    payload.conversation_id = conversation_id
    return await ask_question(
        project_id=project_id,
        payload=payload,
        access=access,
        db=db,
        current_auth=current_auth,
        settings=settings,
        _=None,
    )


@router.get(
    "/projects/{project_id}/assistant/usage",
    response_model=AssistantUsageResponse,
)
async def assistant_usage(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    current_auth: CurrentAuth = Depends(get_current_auth),
    settings: Settings = Depends(get_settings),
) -> AssistantUsageResponse:
    decision = await get_rate_limiter().usage(
        user_id=current_auth.user.id, project_id=project_id
    )
    return AssistantUsageResponse(
        questions_used_today=0,
        daily_tokens_used=decision.daily_tokens_used,
        daily_tokens_remaining=decision.daily_tokens_remaining,
        max_questions_per_minute=settings.assistant_max_questions_per_minute,
        max_daily_tokens=settings.assistant_max_daily_tokens,
        rate_limit_enabled=settings.assistant_rate_limit_enabled,
    )


@router.get(
    "/projects/{project_id}/assistant/config",
    response_model=AssistantConfigResponse,
)
async def assistant_config(
    project_id: UUID,
    access: ProjectAccess = Depends(require_project_reader),
    settings: Settings = Depends(get_settings),
) -> AssistantConfigResponse:
    """Effective assistant configuration. The API key is never part of this response."""
    return AssistantConfigResponse(
        provider=settings.llm_provider,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        max_input_tokens=settings.assistant_max_input_tokens,
        max_history_messages=settings.assistant_max_history_messages,
        top_k=settings.assistant_top_k,
        min_context_score=settings.assistant_min_context_score,
        rate_limit_enabled=settings.assistant_rate_limit_enabled,
    )


def _message_response(
    message, citations, project_id: UUID  # type: ignore[no-untyped-def]
) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        status=message.status,
        sequence=message.sequence,
        llm_provider=message.llm_provider,
        llm_model=message.llm_model,
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens,
        total_tokens=message.total_tokens,
        estimated_cost_usd=message.estimated_cost_usd,
        cost_is_estimate=message.cost_is_estimate,
        rag_duration_ms=message.rag_duration_ms,
        llm_duration_ms=message.llm_duration_ms,
        chunks_retrieved=message.chunks_retrieved,
        error_category=message.error_category,
        grounding_note=message.grounding_note,
        created_at=message.created_at,
        citations=[
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
                deep_link=(
                    f"/projects/{project_id}/sources?source={citation.source_id}"
                    f"&page={citation.page}"
                ),
            )
            for citation in citations
        ],
    )
