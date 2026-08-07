from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import CurrentUserId, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.rag.schemas import ChatRequest


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ApiResponse)
async def chat(
    payload: ChatRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> ApiResponse:
    result = await request.app.state.container.chat.complete(db, user_id, payload)
    return ApiResponse(data=result.model_dump(), traceId=current_trace_id())


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> StreamingResponse:
    service = request.app.state.container.chat

    async def events():
        async for event in service.stream(db, user_id, payload):
            yield f"event: {event['type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
