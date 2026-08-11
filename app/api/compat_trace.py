"""RAGent 前端契约兼容路由: /rag/traces/runs (管理端 Trace 页面)

对应 ragTraceService.ts: traceId/traceName/durationMs/startTime 等字段契约,
与内部 /management/traces 不同 (后者为 user_id 隔离的简版)。
管理端全局视图: 仅 admin 可访问。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.api.dependencies import CurrentAdmin, DbSession
from app.framework.errors import AppError
from app.framework.response import ApiResponse
from app.framework.timeutil import utc_iso
from app.framework.trace import current_trace_id
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
from app.modules.users.models import User


router = APIRouter(prefix="/rag/traces", tags=["trace-compat"])


def run_vo(run: RagTraceRun, user_name: str | None = None) -> dict:
    return {
        "traceId": run.id,
        "traceName": "RAG Chat",
        "entryMethod": "chat/stream",
        "conversationId": run.conversation_id,
        "taskId": None,
        "userName": user_name,
        "username": user_name,
        "userId": str(run.user_id),
        "status": run.status,
        "errorMessage": run.error_message,
        "durationMs": run.elapsed_ms,
        "ttftMs": None,
        "question": run.query,
        # 必须走 utc_iso：created_at 是 naive UTC，直接 isoformat 输出的无时区串
        # 会被浏览器当本地时间解析（UTC+8 差 8 小时）
        "startTime": utc_iso(run.created_at),
        "endTime": None,
    }


def node_vo(node: RagTraceNode) -> dict:
    return {
        "traceId": node.run_id,
        "nodeId": str(node.id),
        "parentNodeId": None,
        "depth": 0,
        "nodeType": node.name,
        "nodeName": node.name,
        "className": "rag",
        "methodName": node.name,
        "status": node.status,
        "errorMessage": None,
        "durationMs": node.elapsed_ms,
        "startTime": None,
        "endTime": None,
        "extraData": node.attributes_json,
    }


@router.get("/runs", response_model=ApiResponse)
def list_runs(
    db: DbSession,
    admin: CurrentAdmin,
    request: Request,
    current: int = 1,
    size: int = 10,
    traceId: str | None = None,
    conversationId: str | None = None,
    taskId: str | None = None,
    status: str | None = None,
) -> ApiResponse:
    statement = select(RagTraceRun, User.username).join(
        User, User.id == RagTraceRun.user_id, isouter=True
    )
    if traceId:
        statement = statement.where(RagTraceRun.id.like(f"%{traceId}%"))
    if conversationId:
        statement = statement.where(RagTraceRun.conversation_id == conversationId)
    if status:
        statement = statement.where(RagTraceRun.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.execute(
            statement.order_by(RagTraceRun.created_at.desc())
            .offset((max(current, 1) - 1) * max(size, 1))
            .limit(min(max(size, 1), 100))
        )
    )
    records = [run_vo(run, user_name) for run, user_name in rows]
    return ApiResponse(
        data={
            "records": records,
            "total": total,
            "size": size,
            "current": current,
            "pages": (total + size - 1) // size if size else 0,
        },
        traceId=current_trace_id(),
    )


@router.get("/runs/{trace_id}", response_model=ApiResponse)
def run_detail(
    trace_id: str, db: DbSession, admin: CurrentAdmin, request: Request
) -> ApiResponse:
    row = db.execute(
        select(RagTraceRun, User.username)
        .join(User, User.id == RagTraceRun.user_id, isouter=True)
        .where(RagTraceRun.id == trace_id)
    ).first()
    if row is None:
        raise AppError("TRACE_NOT_FOUND", "Trace 不存在", 404)
    run, user_name = row
    return ApiResponse(
        data={"run": run_vo(run, user_name)},
        traceId=current_trace_id(),
    )


@router.get("/runs/{trace_id}/nodes", response_model=ApiResponse)
def run_nodes(
    trace_id: str, db: DbSession, admin: CurrentAdmin, request: Request
) -> ApiResponse:
    run = db.get(RagTraceRun, trace_id)
    if run is None:
        raise AppError("TRACE_NOT_FOUND", "Trace 不存在", 404)
    nodes = list(
        db.scalars(
            select(RagTraceNode)
            .where(RagTraceNode.run_id == trace_id)
            .order_by(RagTraceNode.id.asc())
        )
    )
    return ApiResponse(
        data={"runId": trace_id, "nodes": [node_vo(node) for node in nodes]},
        traceId=current_trace_id(),
    )
