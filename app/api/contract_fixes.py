from __future__ import annotations

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
