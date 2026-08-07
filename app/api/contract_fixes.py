from __future__ import annotations

import os

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.compat_trace import node_vo, run_vo
from app.api.dependencies import CurrentAdmin, CurrentUser, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
from app.modules.users.models import User


router = APIRouter(tags=["frontend-contracts"])


def _model_candidate(endpoint) -> dict:
    return {
        "id": endpoint.name,
        "provider": endpoint.name,
        "model": endpoint.model,
        "url": endpoint.base_url,
        "priority": endpoint.priority,
        "enabled": True,
        "supportsThinking": endpoint.model == "mimo-v2.5",
    }


@router.get("/rag/settings")
def rag_settings(user: CurrentUser, request: Request) -> ApiResponse:
    settings = request.app.state.container.settings
    endpoints = settings.chat_endpoints()
    candidates = [_model_candidate(endpoint) for endpoint in endpoints]
    providers = {
        endpoint.name: {
            "url": endpoint.base_url,
            "apiKey": None,
            "endpoints": {"chat": "/chat/completions"},
        }
        for endpoint in endpoints
    }
    default_model = candidates[0]["id"] if candidates else None
    embedding_path = os.getenv("EMBED_MODEL_PATH")
    rerank_path = os.getenv("RERANK_MODEL_PATH")
    return ApiResponse(
        data={
            "upload": {
                "maxFileSize": int(os.getenv("MAX_UPLOAD_FILE_SIZE", str(50 * 1024 * 1024))),
                "maxRequestSize": int(os.getenv("MAX_UPLOAD_REQUEST_SIZE", str(60 * 1024 * 1024))),
            },
            "rag": {
                "default": {
                    "collectionName": os.getenv("MILVUS_COLLECTION", "ragent_chunks_v2"),
                    "dimension": int(os.getenv("EMBED_DIMENSION", "512")),
                    "metricType": os.getenv("MILVUS_METRIC_TYPE", "COSINE"),
                },
                "queryRewrite": {"enabled": True},
                "rateLimit": {
                    "global": {
                        "enabled": False,
                        "maxConcurrent": 8,
                        "maxWaitSeconds": 30,
                        "leaseSeconds": 180,
                        "pollIntervalMs": 100,
                    }
                },
                "memory": {
                    "historyKeepTurns": 10,
                    "summaryStartTurns": 20,
                    "summaryEnabled": False,
                    "summaryMaxChars": 2000,
                    "titleMaxLength": 30,
                },
            },
            "ai": {
                "providers": providers,
                "selection": {
                    "failureThreshold": settings.circuit_failure_threshold,
                    "openDurationMs": int(settings.circuit_recovery_seconds * 1000),
                },
                "stream": {"messageChunkSize": 1},
                "chat": {
                    "defaultModel": default_model,
                    "candidates": candidates,
                    "defaultTier": "default",
                    "deepThinkingTier": "thinking",
                    "tiers": {
                        "default": {"candidates": [item["id"] for item in candidates]},
                        "thinking": {
                            "candidates": [
                                item["id"] for item in candidates if item["supportsThinking"]
                            ]
                        },
                    },
                },
                "embedding": {
                    "defaultModel": "local-embedding" if embedding_path else None,
                    "candidates": (
                        [{
                            "id": "local-embedding",
                            "provider": "local",
                            "model": embedding_path,
                            "dimension": int(os.getenv("EMBED_DIMENSION", "512")),
                            "enabled": True,
                        }]
                        if embedding_path
                        else []
                    ),
                    "defaultTier": None,
                    "deepThinkingTier": None,
                    "tiers": None,
                },
                "rerank": {
                    "defaultModel": "local-rerank" if rerank_path else None,
                    "candidates": (
                        [{
                            "id": "local-rerank",
                            "provider": "local",
                            "model": rerank_path,
                            "enabled": True,
                        }]
                        if rerank_path
                        else []
                    ),
                    "defaultTier": None,
                    "deepThinkingTier": None,
                    "tiers": None,
                },
            },
        },
        traceId=current_trace_id(),
    )


def _trace_row(db, trace_id: str):
    row = db.execute(
        select(RagTraceRun, User.username)
        .join(User, User.id == RagTraceRun.user_id, isouter=True)
        .where(RagTraceRun.id == trace_id)
    ).first()
    if row is None:
        raise AppError("TRACE_NOT_FOUND", "Trace 不存在", 404)
    return row


def _trace_nodes(db, trace_id: str) -> list[dict]:
    nodes = list(
        db.scalars(
            select(RagTraceNode)
            .where(RagTraceNode.run_id == trace_id)
            .order_by(RagTraceNode.id.asc())
        )
    )
    return [node_vo(node) for node in nodes]


@router.get("/rag/traces/runs/{trace_id}")
def trace_detail(trace_id: str, db: DbSession, admin: CurrentAdmin) -> ApiResponse:
    run, username = _trace_row(db, trace_id)
    return ApiResponse(
        data={"run": run_vo(run, username), "nodes": _trace_nodes(db, trace_id)},
        traceId=current_trace_id(),
    )


@router.get("/rag/traces/runs/{trace_id}/nodes")
def trace_nodes(trace_id: str, db: DbSession, admin: CurrentAdmin) -> ApiResponse:
    _trace_row(db, trace_id)
    return ApiResponse(data=_trace_nodes(db, trace_id), traceId=current_trace_id())


@router.get("/rag/sample-questions", response_model=ApiResponse)
def public_sample_questions(user: CurrentUser) -> ApiResponse:
    """聊天首页可供所有登录用户读取；未配置时由前端使用内置推荐问法。"""
    return ApiResponse(data=[], traceId=current_trace_id())


_NOT_IMPLEMENTED_MODULES = (
    ("agents", "/agents"),
    ("dashboard", "/admin/dashboard"),
    ("biz-change-logs", "/biz-change-logs"),
    ("ingestion-pipelines", "/ingestion/pipelines"),
    ("ingestion-tasks", "/ingestion/tasks"),
    ("intent-tree", "/intent-tree"),
    ("knowledge-graph", "/admin/kg"),
    ("query-term-mappings", "/mappings"),
    ("sample-questions", "/sample-questions"),
)


for _module_name, _prefix in _NOT_IMPLEMENTED_MODULES:

    @router.api_route(
        _prefix,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def not_implemented_root(
        admin: CurrentAdmin, module_name: str = _module_name
    ) -> ApiResponse:
        raise AppError(
            "NOT_IMPLEMENTED",
            f"模块 '{module_name}' 尚未在 Python 后端实现",
            501,
            {"module": module_name},
        )

    @router.api_route(
        _prefix + "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def not_implemented_path(
        path: str, admin: CurrentAdmin, module_name: str = _module_name
    ) -> ApiResponse:
        raise AppError(
            "NOT_IMPLEMENTED",
            f"模块 '{module_name}' 尚未在 Python 后端实现",
            501,
            {"module": module_name},
        )
