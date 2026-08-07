from __future__ import annotations

import json

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.conversations.models import Message
from app.modules.rag.task_registry import registry as task_registry


router = APIRouter(prefix="", tags=["chat-compat"])


@router.post("/rag/v3/stop", response_model=ApiResponse)
def stop_task(
    taskId: str, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    cancelled = task_registry.cancel(taskId, user.id)
    return ApiResponse(data={"cancelled": cancelled}, traceId=current_trace_id())


class FeedbackRequest(BaseModel):
    vote: int = Field(ge=-1, le=1)


def _require_owned_message(db, message_id: int, user) -> Message:
    message = db.get(Message, message_id)
    if not message or message.user_id != user.id or message.role != "assistant":
        raise AppError("MESSAGE_NOT_FOUND", "消息不存在或无权操作", 404)
    return message


@router.post("/conversations/messages/{message_id}/feedback", response_model=ApiResponse)
def submit_feedback(
    message_id: int,
    payload: FeedbackRequest,
    db: DbSession,
    user: CurrentUser,
    request: Request,
) -> ApiResponse:
    message = _require_owned_message(db, message_id, user)
    message.vote = payload.vote
    db.commit()
    return ApiResponse(data={"vote": message.vote}, traceId=current_trace_id())


@router.delete("/conversations/messages/{message_id}/feedback", response_model=ApiResponse)
def cancel_feedback(
    message_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    message = _require_owned_message(db, message_id, user)
    message.vote = None
    db.commit()
    return ApiResponse(data={"vote": None}, traceId=current_trace_id())


@router.post(
    "/conversations/messages/{message_id}/recommended-questions",
    response_model=ApiResponse,
)
async def recommended_questions(
    message_id: int, db: DbSession, user: CurrentUser, request: Request
) -> ApiResponse:
    message = _require_owned_message(db, message_id, user)
    model_router = request.app.state.container.model_router
    questions: list[str] = []
    failed = False
    message.recommended_questions_status = "GENERATING"
    message.recommended_questions_error = None
    db.commit()
    if model_router is not None:
        from app.infra_ai.contracts import ChatMessage, ChatRequest as ModelChatRequest

        try:
            result = await model_router.complete(
                ModelChatRequest(
                    messages=[
                        ChatMessage(
                            "system",
                            "根据下面的回答生成 3 个简短的自然语言追问问题，"
                            "每行一个，只输出问题本身，不要编号和多余文字。",
                        ),
                        ChatMessage("user", message.content[:2000]),
                    ],
                    temperature=0.7,
                    max_tokens=128,
                )
            )
            questions = [
                line.strip()
                for line in result.splitlines()
                if line.strip() and len(line.strip()) <= 60
            ][:3]
        except Exception as exc:  # noqa: BLE001
            failed = True
            questions = []
            message.recommended_questions_error = str(exc)[:500]
    message.recommended_questions_json = json.dumps(questions, ensure_ascii=False)
    status = "FAILED" if failed else ("SUCCESS" if questions else "EMPTY")
    message.recommended_questions_status = status
    db.commit()
    return ApiResponse(
        data={"status": status, "questions": questions}, traceId=current_trace_id()
    )
