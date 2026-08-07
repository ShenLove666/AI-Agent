from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import DbSession
from app.framework.config import Settings
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.rag.schemas import ChatRequest
from app.modules.rag.task_registry import registry as task_registry


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

    @router.get("/rag/v3/chat")
    async def ragent_chat_stream(
        request: Request,
        db: DbSession,
        question: str,
        conversationId: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        if not authorization:
            raise AppError("INVALID_TOKEN", "认证失效，请重新登录", 401)
        token = authorization.removeprefix("Bearer ").strip()
        user_id = request.app.state.container.auth.decode_user_id(token)
        service = request.app.state.container.chat
        payload = ChatRequest(question=question, conversation_id=conversationId)

        task_id = uuid.uuid4().hex
        cancel_event = task_registry.register(task_id)

        async def events():
            citations: list[dict] = []
            interrupted = False
            try:
                async for event in service.stream(db, user_id, payload):
                    if cancel_event.is_set():
                        interrupted = True
                        break
                    event_type = event["type"]
                    data = event["data"]
                    if event_type == "conversation":
                        yield _sse("meta", {"conversationId": data["id"], "taskId": task_id})
                    elif event_type == "token":
                        yield _sse("message", {"type": "response", "delta": data})
                    elif event_type == "citations":
                        citations = [_source_ref(item, index) for index, item in enumerate(data, 1)]
                    elif event_type == "done":
                        yield _sse("finish", {"sources": citations, "messageStatus": "NORMAL"})
                        yield _sse("done", {})
                if interrupted:
                    yield _sse(
                        "finish",
                        {"sources": citations, "messageStatus": "INTERRUPTED"},
                    )
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


def _source_ref(item: dict, index: int) -> dict:
    metadata = item.get("metadata") or {}
    return {
        "index": index,
        "docId": str(metadata.get("document_id") or item.get("id") or ""),
        "docName": metadata.get("filename") or item.get("source") or "知识库文档",
        "excerpt": item.get("content") or "",
    }
