from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.dependencies import CurrentAdmin, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.conversations.models import Conversation, Message
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
from app.modules.users.models import User


router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])

DashboardWindow = Literal["24h", "7d", "30d"]
DashboardGranularity = Literal["hour", "day"]

_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _now() -> datetime:
    # Existing models store naive UTC datetimes. Keep comparisons compatible,
    # while converting timestamps to UTC at the API boundary.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _count(db, model, start: datetime | None = None, end: datetime | None = None) -> int:
    statement = select(func.count()).select_from(model)
    if start is not None:
        statement = statement.where(model.created_at >= start)
    if end is not None:
        statement = statement.where(model.created_at < end)
    return int(db.scalar(statement) or 0)


def _distinct_users(db, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(Message.user_id))).where(
                Message.created_at >= start,
                Message.created_at < end,
            )
        )
        or 0
    )


def _kpi(value: int, previous: int) -> dict[str, int | float]:
    delta = value - previous
    delta_pct = round(delta / previous * 100, 2) if previous else (100.0 if value else 0.0)
    return {"value": value, "delta": delta, "deltaPct": delta_pct}


def _window_bounds(window: DashboardWindow) -> tuple[datetime, datetime, datetime]:
    end = _now()
    start = end - _WINDOWS[window]
    return start - _WINDOWS[window], start, end


@router.get("/overview")
def overview(
    db: DbSession,
    admin: CurrentAdmin,
    window: DashboardWindow = "24h",
) -> ApiResponse:
    previous_start, start, end = _window_bounds(window)
    users_total = _count(db, User)
    users_current = _count(db, User, start, end)
    sessions_total = _count(db, Conversation)
    messages_total = _count(db, Message)
    active_users = _distinct_users(db, start, end)
    previous_active_users = _distinct_users(db, previous_start, start)
    sessions = _count(db, Conversation, start, end)
    previous_sessions = _count(db, Conversation, previous_start, start)
    messages = _count(db, Message, start, end)
    previous_messages = _count(db, Message, previous_start, start)

    return ApiResponse(
        data={
            "window": window,
            "compareWindow": f"previous-{window}",
            "updatedAt": int(end.replace(tzinfo=timezone.utc).timestamp() * 1000),
            "kpis": {
                "totalUsers": _kpi(users_total, max(users_total - users_current, 0)),
                "activeUsers": _kpi(active_users, previous_active_users),
                "totalSessions": _kpi(sessions_total, max(sessions_total - sessions, 0)),
                "sessions24h": _kpi(sessions, previous_sessions),
                "totalMessages": _kpi(messages_total, max(messages_total - messages, 0)),
                "messages24h": _kpi(messages, previous_messages),
            },
        },
        traceId=current_trace_id(),
    )


def _percent(part: int, total: int) -> float:
    return round(part / total * 100, 2) if total else 0.0


_COMMERCE_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("订单物流", ("订单", "物流", "快递", "配送", "发货", "送达")),
    ("售后服务", ("退款", "退货", "换货", "售后", "投诉", "赔付")),
    ("商品咨询", ("商品", "规格", "尺码", "库存", "有货", "保质期")),
    ("营销活动", ("优惠", "满减", "红包", "活动", "折扣", "促销")),
    ("门店经营", ("门店", "商家", "营业", "上架", "销量", "转化")),
)


def _commerce_intent(content: str) -> str:
    """可解释的电商意图基线，后续可无缝替换为模型分类器。"""
    normalized = (content or "").lower()
    for label, keywords in _COMMERCE_INTENTS:
        if any(keyword in normalized for keyword in keywords):
            return label
    return "其他咨询"


def _trace_rows(db, start: datetime, end: datetime) -> list[RagTraceRun]:
    return list(
        db.scalars(
            select(RagTraceRun).where(
                RagTraceRun.created_at >= start,
                RagTraceRun.created_at < end,
            )
        )
    )


def _no_document_run_ids(db, start: datetime, end: datetime) -> set[str]:
    nodes = db.scalars(
        select(RagTraceNode).where(
            RagTraceNode.name == "retrieval",
            RagTraceNode.created_at >= start,
            RagTraceNode.created_at < end,
        )
    )
    result: set[str] = set()
    for node in nodes:
        try:
            attributes = json.loads(node.attributes_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if attributes.get("result_count") == 0:
            result.add(node.run_id)
    return result


@router.get("/performance")
def performance(
    db: DbSession,
    admin: CurrentAdmin,
    window: DashboardWindow = "24h",
) -> ApiResponse:
    _, start, end = _window_bounds(window)
    runs = _trace_rows(db, start, end)
    completed = [run for run in runs if run.status != "running"]
    latencies = sorted(float(run.elapsed_ms) for run in completed if run.elapsed_ms is not None)
    successful = sum(run.status == "success" for run in completed)
    failed = sum(run.status == "failed" for run in completed)
    no_document = len(_no_document_run_ids(db, start, end) & {run.id for run in completed})
    slow = sum((run.elapsed_ms or 0) >= 15_000 for run in completed)
    p95_index = max(math.ceil(len(latencies) * 0.95) - 1, 0)

    return ApiResponse(
        data={
            "window": window,
            "avgLatencyMs": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p95LatencyMs": round(latencies[p95_index], 2) if latencies else 0,
            "successRate": _percent(successful, len(completed)),
            "errorRate": _percent(failed, len(completed)),
            "noDocRate": _percent(no_document, len(completed)),
            "slowRate": _percent(slow, len(completed)),
        },
        traceId=current_trace_id(),
    )


@router.get("/operations")
def operations(
    db: DbSession,
    admin: CurrentAdmin,
    window: DashboardWindow = "7d",
) -> ApiResponse:
    """聚合商家使用、回答质量和待优化问题，形成运营闭环。"""
    _, start, end = _window_bounds(window)
    total_accounts = _count(db, User)
    active_accounts = _distinct_users(db, start, end)

    assistant_messages = list(
        db.scalars(
            select(Message).where(
                Message.role == "assistant",
                Message.created_at >= start,
                Message.created_at < end,
            )
        )
    )
    user_messages = list(
        db.scalars(
            select(Message).where(
                Message.role == "user",
                Message.created_at >= start,
                Message.created_at < end,
            )
        )
    )
    voted = [message for message in assistant_messages if message.vote in {-1, 1}]
    positive = sum(message.vote == 1 for message in voted)
    negative = sum(message.vote == -1 for message in voted)

    runs = [run for run in _trace_rows(db, start, end) if run.status != "running"]
    failed = sum(run.status == "failed" for run in runs)
    slow = sum((run.elapsed_ms or 0) >= 15_000 for run in runs)
    no_document = len(_no_document_run_ids(db, start, end) & {run.id for run in runs})

    intent_counts: dict[str, int] = defaultdict(int)
    for message in user_messages:
        intent_counts[_commerce_intent(message.content)] += 1
    intent_distribution = [
        {"name": name, "count": count, "rate": _percent(count, len(user_messages))}
        for name, count in sorted(intent_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    issue_specs = (
        ("知识未命中", no_document, len(runs), "高", "补齐高频问法对应知识，并检查切块与召回参数"),
        ("用户负反馈", negative, len(voted), "高", "抽样复盘点踩回答，沉淀标注集并迭代提示词"),
        ("响应过慢", slow, len(runs), "中", "定位检索与生成耗时，优化超时和模型路由"),
        ("执行失败", failed, len(runs), "高", "按 Trace 排查供应商、检索和生成节点异常"),
    )
    issues = [
        {"name": name, "count": count, "rate": _percent(count, total), "priority": priority, "action": action}
        for name, count, total, priority, action in issue_specs
    ]

    return ApiResponse(
        data={
            "window": window,
            "updatedAt": int(end.replace(tzinfo=timezone.utc).timestamp() * 1000),
            "kpis": {
                "merchantAccounts": total_accounts,
                "activeMerchants": active_accounts,
                "penetrationRate": _percent(active_accounts, total_accounts),
                "aiResponses": len(assistant_messages),
                "feedbackCoverage": _percent(len(voted), len(assistant_messages)),
                "positiveRate": _percent(positive, len(voted)),
                "knowledgeHitRate": round(100 - _percent(no_document, len(runs)), 2) if runs else 0.0,
            },
            "quality": {
                "evaluated": len(voted),
                "positive": positive,
                "negative": negative,
                "traceRuns": len(runs),
            },
            "intentDistribution": intent_distribution,
            "issues": issues,
            "methodology": {
                "merchantProxy": "当前以注册账号代表商家账号，以窗口内发起消息的账号代表活跃商家。",
                "intentMethod": "基于可解释关键词规则归类，可替换为模型分类器。",
                "slowThresholdMs": 15000,
            },
        },
        traceId=current_trace_id(),
    )


def _bucket_start(value: datetime, granularity: DashboardGranularity) -> datetime:
    if granularity == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _buckets(start: datetime, end: datetime, granularity: DashboardGranularity) -> list[datetime]:
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    current = _bucket_start(start, granularity)
    result: list[datetime] = []
    while current <= end:
        result.append(current)
        current += step
    return result


def _epoch_ms(value: datetime) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _series(name: str, buckets: list[datetime], values: dict[datetime, float]) -> dict:
    return {
        "name": name,
        "data": [
            {"ts": _epoch_ms(bucket), "value": round(values.get(bucket, 0), 2)}
            for bucket in buckets
        ],
    }


@router.get("/trends")
def trends(
    db: DbSession,
    admin: CurrentAdmin,
    metric: Literal["sessions", "messages", "activeUsers", "avgLatency", "quality"],
    window: DashboardWindow = "7d",
    granularity: DashboardGranularity = "day",
) -> ApiResponse:
    _, start, end = _window_bounds(window)
    bucket_list = _buckets(start, end, granularity)

    if metric in {"sessions", "messages"}:
        model = Conversation if metric == "sessions" else Message
        rows = db.scalars(
            select(model.created_at).where(model.created_at >= start, model.created_at < end)
        )
        counts: dict[datetime, float] = defaultdict(float)
        for created_at in rows:
            counts[_bucket_start(created_at, granularity)] += 1
        series = [_series("会话数" if metric == "sessions" else "消息数", bucket_list, counts)]
    elif metric == "activeUsers":
        rows = db.execute(
            select(Message.created_at, Message.user_id).where(
                Message.created_at >= start, Message.created_at < end
            )
        )
        users: dict[datetime, set[int]] = defaultdict(set)
        for created_at, user_id in rows:
            users[_bucket_start(created_at, granularity)].add(user_id)
        series = [
            _series("活跃用户", bucket_list, {key: len(value) for key, value in users.items()})
        ]
    else:
        runs = _trace_rows(db, start, end)
        grouped: dict[datetime, list[RagTraceRun]] = defaultdict(list)
        for run in runs:
            grouped[_bucket_start(run.created_at, granularity)].append(run)
        if metric == "avgLatency":
            values = {
                key: sum(run.elapsed_ms or 0 for run in rows) / len(rows)
                for key, rows in grouped.items()
                if rows
            }
            series = [_series("平均延迟", bucket_list, values)]
        else:
            no_document_ids = _no_document_run_ids(db, start, end)
            error_rates: dict[datetime, float] = {}
            no_doc_rates: dict[datetime, float] = {}
            for key, rows in grouped.items():
                completed = [run for run in rows if run.status != "running"]
                error_rates[key] = _percent(
                    sum(run.status == "failed" for run in completed), len(completed)
                )
                no_doc_rates[key] = _percent(
                    sum(run.id in no_document_ids for run in completed), len(completed)
                )
            series = [
                _series("错误率", bucket_list, error_rates),
                _series("无知识率", bucket_list, no_doc_rates),
            ]

    return ApiResponse(
        data={
            "metric": metric,
            "window": window,
            "granularity": granularity,
            "series": series,
        },
        traceId=current_trace_id(),
    )
