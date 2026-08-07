from __future__ import annotations

import json

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.dependencies import CurrentAdmin, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun


router = APIRouter(prefix="/management", tags=["management"])


@router.get("/traces", response_model=ApiResponse)
def list_traces(
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
    limit: int = 50,
) -> ApiResponse:
    runs = list(
        db.scalars(
            select(RagTraceRun)
            .where(RagTraceRun.user_id == admin.id)
            .order_by(RagTraceRun.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    )
    return ApiResponse(
        data=[
            {
                "id": run.id,
                "conversationId": run.conversation_id,
                "query": run.query,
                "rewrittenQuery": run.rewritten_query,
                "status": run.status,
                "elapsedMs": run.elapsed_ms,
                "error": run.error_message,
                "createdAt": run.created_at.isoformat(),
            }
            for run in runs
        ],
        traceId=current_trace_id(),
    )
@router.get("/traces/{run_id}", response_model=ApiResponse)
def trace_detail(
    run_id: str,
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
) -> ApiResponse:
    run = db.scalar(
        select(RagTraceRun).where(
            RagTraceRun.id == run_id, RagTraceRun.user_id == admin.id
        )
    )
    if run is None:
        from app.framework.errors import AppError

        raise AppError("TRACE_NOT_FOUND", "Trace 不存在", 404)
    nodes = list(
        db.scalars(
            select(RagTraceNode)
            .where(RagTraceNode.run_id == run_id)
            .order_by(RagTraceNode.id.asc())
        )
    )
    return ApiResponse(
        data={
            "id": run.id,
            "query": run.query,
            "rewrittenQuery": run.rewritten_query,
            "status": run.status,
            "elapsedMs": run.elapsed_ms,
            "error": run.error_message,
            "nodes": [
                {
                    "name": node.name,
                    "status": node.status,
                    "elapsedMs": node.elapsed_ms,
                    "attributes": json.loads(node.attributes_json or "{}"),
                }
                for node in nodes
            ],
        },
        traceId=current_trace_id(),
    )
@router.get("/models", response_model=ApiResponse)
def model_health(admin: CurrentAdmin, request: Request) -> ApiResponse:
    container = request.app.state.container
    providers = []
    if container.model_router:
        for provider in container.model_router.providers:
            snapshot = provider.breaker.snapshot()
            providers.append(
                {
                    "name": provider.model.name,
                    "priority": provider.priority,
                    "circuitState": snapshot.state.value,
                    "failures": snapshot.failures,
                }
            )
    return ApiResponse(
        data={
            "chatProviders": providers,
            "retrievalChannels": [channel.name for channel in container.retrieval.channels],
        },
        traceId=current_trace_id(),
    )
@router.get("/settings", response_model=ApiResponse)
def system_settings(admin: CurrentAdmin, request: Request) -> ApiResponse:
    container = request.app.state.container
    settings = container.settings
    return ApiResponse(
        data={
            "environment": settings.environment,
            "retrieval": {
                "candidateLimit": settings.retrieval_candidate_limit,
                "contextLimit": settings.retrieval_context_limit,
                "timeoutSeconds": settings.retrieval_timeout_seconds,
                "channels": [channel.name for channel in container.retrieval.channels],
            },
            "features": {
                "queryRewrite": True,
                "ragTrace": True,
                "rerank": any(
                    processor.__class__.__name__ == "RerankPostProcessor"
                    for processor in container.retrieval.postprocessors
                ),
            },
        },
        traceId=current_trace_id(),
    )
