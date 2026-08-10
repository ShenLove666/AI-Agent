from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator

from app.api.dependencies import CurrentUser, DbSession
from app.framework.config import Settings
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.rag.schemas import ChatRequest
from app.api.source_refs import source_ref
from app.modules.rag.task_registry import registry as task_registry


class RagentChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    conversationId: str | None = None
    requestId: str | None = Field(default=None, min_length=8, max_length=64)
    deepThinking: bool = False
    ragEnabled: bool = True
    knowledgeBaseIds: list[StrictInt] = Field(default_factory=list)
    turnId: int | None = Field(default=None, gt=0)
    regenerate: bool = False

    @field_validator("knowledgeBaseIds")
    @classmethod
    def validate_scope(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("knowledgeBaseIds 必须全部为正整数")
        if len(value) != len(set(value)):
            raise ValueError("knowledgeBaseIds 不能重复")
        return value

    @model_validator(mode="after")
    def validate_regeneration(self):
        if self.regenerate and self.turnId is None:
            raise ValueError("regenerate=true 时必须提供 turnId")
        return self


def create_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=ApiResponse)
    async def health() -> ApiResponse:
        return ApiResponse(
            data={
                "status": "up",
                "application": settings.app_name,
                "environment": settings.environment,
                "architecture": "modular-monolith",
                "runtime": "python",
            },
            traceId=current_trace_id(),
        )

    @router.get("/architecture", response_model=ApiResponse)
    async def architecture() -> ApiResponse:
        return ApiResponse(
            data={
                "framework": ["config", "errors", "trace", "http", "sse"],
                "infraAi": ["chat", "embedding", "rerank", "routing", "circuit-breaker"],
                "modules": ["rag", "retrieval", "ingestion", "knowledge", "conversation", "user"],
            },
            traceId=current_trace_id(),
        )

    @router.post("/rag/v3/chat")
    async def ragent_chat_stream(
        payload: RagentChatStreamRequest,
        request: Request,
        db: DbSession,
        user: CurrentUser,
    ) -> StreamingResponse:
        service = request.app.state.container.chat
        chat_request = ChatRequest(
            question=payload.question,
            conversation_id=payload.conversationId,
            request_id=payload.requestId,
            deep_thinking=payload.deepThinking,
            rag_enabled=payload.ragEnabled,
            knowledge_base_ids=payload.knowledgeBaseIds,
            turn_id=payload.turnId,
            regenerate=payload.regenerate,
        )
        task_id = uuid.uuid4().hex

        async def events():
            citations: list[dict] = []
            cancel_event = task_registry.register(task_id, user.id)
            # SSE 一连接就下发 taskId（仅 taskId），让前端在 prepare 阶段即可停止；
            # conversation 事件到达后再补发一次全量 meta（含 conversationId）。
            yield _sse("meta", {"taskId": task_id})
            try:
                async for event in service.stream(db, user.id, chat_request, cancel_event):
                    event_type = event["type"]
                    data = event["data"]
                    if event_type == "conversation":
                        yield _sse(
                            "meta",
                            {
                                "conversationId": data["id"],
                                "taskId": task_id,
                                "title": data.get("title"),
                                "turnId": data.get("turn_id"),
                                "userMessageId": data.get("user_message_id"),
                            },
                        )
                    elif event_type == "token":
                        yield _sse("message", {"type": "response", "delta": data})
                    elif event_type == "thinking":
                        yield _sse("message", {"type": "think", "delta": data})
                    elif event_type == "citations":
                        citations = [source_ref(item, index) for index, item in enumerate(data, 1)]
                    elif event_type == "agent_progress":
                        yield _sse("agent_progress", {**data, "taskId": task_id})
                    elif event_type == "done":
                        yield _sse(
                            "finish",
                            {
                                "messageId": data.get("message_id"),
                                "sources": citations,
                                "messageStatus": "NORMAL",
                                "turnId": data.get("turn_id"),
                                "userMessageId": data.get("user_message_id"),
                                "version": data.get("version"),
                            },
                        )
                        yield _sse("done", {})
                    elif event_type == "cancelled":
                        yield _sse(
                            "cancel",
                            {
                                "messageId": data.get("message_id"),
                                "sources": citations,
                                "messageStatus": "INTERRUPTED",
                                "turnId": data.get("turn_id"),
                                "userMessageId": data.get("user_message_id"),
                                "version": data.get("version"),
                            },
                        )
                        yield _sse("done", {})
                    elif event_type == "error":
                        yield _sse(
                            "error",
                            {
                                "messageId": data.get("message_id"),
                                "error": data.get("error"),
                                "code": data.get("code"),
                                "turnId": data.get("turn_id"),
                                "userMessageId": data.get("user_message_id"),
                                "version": data.get("version"),
                            },
                        )
                        yield _sse("done", {})
            except AppError as exc:
                yield _sse("error", {"error": exc.message, "code": exc.code})
                yield _sse("done", {})
            except Exception:
                yield _sse("error", {"error": "生成失败，请稍后重试", "code": "STREAM_FAILED"})
                yield _sse("done", {})
            finally:
                task_registry.unregister(task_id)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
