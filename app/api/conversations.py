from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, DbSession
from app.api.source_refs import source_ref
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.conversations.models import ConversationTurn, Message
from app.modules.rag.schemas import ChatRequest


router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=200)


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def serialize_conversation(item):
    # 同时提供新旧两套字段: id (旧) 与 conversationId/lastTime (RAGent 契约)
    return {
        "id": item.id,
        "conversationId": item.id,
        "title": item.title,
        "lastTime": (item.last_message_at or item.updated_at).isoformat(),
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def serialize_message(item: Message, versions: list[Message] | None = None) -> dict:
    def sources(citations_json: str | None) -> list[dict]:
        raw = json.loads(citations_json) if citations_json else []
        return [source_ref(citation, index) for index, citation in enumerate(raw, 1)]

    return {
        "id": item.id,
        "conversationId": item.conversation_id,
        "turnId": item.turn_id,
        "version": item.version,
        "role": item.role,
        "content": item.content,
        "citations": item.citations_json,
        "sources": sources(item.citations_json),
        "messageStatus": item.message_status or "NORMAL",
        "vote": item.vote,
        "thinkingContent": item.thinking_content,
        "thinkingDuration": (
            round(item.thinking_duration_ms / 1000, 2)
            if item.thinking_duration_ms is not None
            else None
        ),
        "answerVersions": [
            {
                "id": version.id,
                "version": version.version,
                "content": version.content,
                "sources": sources(version.citations_json),
                "messageStatus": version.message_status or "NORMAL",
                "vote": version.vote,
                "thinkingContent": version.thinking_content,
                "thinkingDuration": (
                    round(version.thinking_duration_ms / 1000, 2)
                    if version.thinking_duration_ms is not None
                    else None
                ),
                "createdAt": version.created_at.isoformat(),
            }
            for version in (versions or [])
        ],
        "recommendedQuestions": (
            json.loads(item.recommended_questions_json)
            if item.recommended_questions_json
            else None
        ),
        "recommendedQuestionsStatus": item.recommended_questions_status
        or "NOT_REQUESTED",
        "recommendedQuestionsError": item.recommended_questions_error,
        "createTime": item.created_at.isoformat(),
        "createdAt": item.created_at.isoformat(),
    }


@router.post("", response_model=ApiResponse, status_code=201)
def create_conversation(
    payload: ConversationCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    item = request.app.state.container.conversations.create(db, user_id, payload.title)
    return ApiResponse(data=serialize_conversation(item), traceId=current_trace_id())


@router.get("", response_model=ApiResponse)
def list_conversations(
    db: DbSession, user_id: CurrentUserId, request: Request
) -> ApiResponse:
    items = request.app.state.container.conversations.list(db, user_id)
    return ApiResponse(
        data=[serialize_conversation(item) for item in items], traceId=current_trace_id()
    )


@router.get("/{conversation_id}/messages", response_model=ApiResponse)
def list_messages(
    conversation_id: str,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    items = request.app.state.container.conversations.messages(db, conversation_id, user_id)
    by_id = {item.id: item for item in items}
    turns = list(
        db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.sequence.asc())
        )
    )
    displayed: list[tuple[Message, list[Message] | None]] = [
        (item, None) for item in items if item.turn_id is None
    ]
    for turn in turns:
        user_message = by_id.get(turn.user_message_id)
        versions = sorted(
            (
                item
                for item in items
                if item.turn_id == turn.id and item.role == "assistant"
            ),
            key=lambda item: (item.version or 0, item.id),
        )
        assistant = by_id.get(turn.active_assistant_message_id) or (
            versions[-1] if versions else None
        )
        if user_message is not None:
            displayed.append((user_message, None))
        if assistant is not None:
            displayed.append((assistant, versions))
    displayed.sort(key=lambda pair: (pair[0].created_at, pair[0].id))
    return ApiResponse(
        data=[serialize_message(item, versions) for item, versions in displayed],
        traceId=current_trace_id(),
    )


@router.post("/turns/{turn_id}/regenerate", response_model=ApiResponse)
async def regenerate_turn(
    turn_id: int,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    conversations = request.app.state.container.conversations
    turn = conversations.require_owned_turn(db, turn_id, user_id)
    user_message = db.get(Message, turn.user_message_id)
    if user_message is None:
        from app.framework.errors import AppError

        raise AppError("TURN_USER_MESSAGE_MISSING", "轮次缺少用户消息", 409)
    result = await request.app.state.container.chat.complete(
        db,
        user_id,
        ChatRequest(
            question=user_message.content,
            conversation_id=turn.conversation_id,
            request_id=uuid.uuid4().hex,
            deep_thinking=turn.deep_thinking,
            rag_enabled=turn.rag_enabled,
            knowledge_base_ids=json.loads(turn.knowledge_base_ids_json or "[]"),
            turn_id=turn.id,
            regenerate=True,
        ),
    )
    return ApiResponse(data=result.model_dump(by_alias=True), traceId=current_trace_id())


@router.patch("/{conversation_id}", response_model=ApiResponse)
def rename_conversation(
    conversation_id: str,
    payload: ConversationRenameRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    item = request.app.state.container.conversations.rename(
        db, conversation_id, user_id, payload.title.strip()
    )
    return ApiResponse(data=serialize_conversation(item), traceId=current_trace_id())


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> Response:
    request.app.state.container.conversations.delete(db, conversation_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
