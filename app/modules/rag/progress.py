"""Agent 执行进度事件：事件结构、中文展示映射与进度收集工具。

所有面向用户的文本（title/detail/argumentsSummary/tool label）的中文映射
以本模块为唯一权威来源；节点与 service 禁止直接向用户透出内部英文工具名、
Planner rationale 或工具参数的完整 JSON 原文。
"""

from __future__ import annotations

import itertools
import time
from typing import Any, Awaitable, Callable, Literal, TypedDict

Phase = Literal[
    "rewrite",
    "planning",
    "tool",
    "review",
    "replan",
    "generation",
    "complete",
]
Status = Literal[
    "pending",
    "running",
    "completed",
    "warning",
    "failed",
    "cancelled",
]


class ToolProgress(TypedDict, total=False):
    name: str
    label: str
    status: str
    argumentsSummary: str
    durationMs: int
    evidenceCount: int


class ProgressMetrics(TypedDict, total=False):
    evidenceCount: int
    coverage: float
    conflictCount: int


class AgentProgressEvent(TypedDict, total=False):
    seq: int
    phase: Phase
    status: Status
    agent: str
    plan: int
    title: str
    detail: str
    tool: ToolProgress
    metrics: ProgressMetrics
    timestamp: float


ProgressSink = Callable[[AgentProgressEvent], Awaitable[None]]


# 工具的中文展示名（唯一权威来源）。禁止直接显示 Python 函数名/内部工具名。
TOOL_LABELS: dict[str, str] = {
    "commerce.search_association_rules": "商品关联分析",
    "commerce.get_product_metrics": "商品经营指标",
    "commerce.get_order": "订单信息查询",
    "commerce.get_delivery_status": "配送状态查询",
    "commerce.get_refund_status": "退款状态查询",
    "commerce.get_customer_history": "顾客历史查询",
    "knowledge.search": "知识库检索",
    "knowledge.get_document": "知识文档读取",
    "support.search_cases": "客服案例检索",
    "support.get_quality_metrics": "客服质量分析",
    "support.get_knowledge_gaps": "知识缺口分析",
}

DEFAULT_TOOL_LABEL = "业务数据查询"


def tool_label(name: str) -> str:
    """工具的中文展示名；未知工具回退到通用文案，禁止透出内部英文名。"""
    return TOOL_LABELS.get(name, DEFAULT_TOOL_LABEL)


# 各阶段状态的标准中文文案（唯一权威来源）。
PHASE_TEXTS: dict[tuple[Phase, Status], str] = {
    ("planning", "running"): "正在制定查询计划",
    ("planning", "completed"): "查询计划已制定",
    ("tool", "running"): "正在查询数据",
    ("tool", "completed"): "查询完成",
    ("review", "running"): "正在核验证据",
    ("review", "completed"): "证据已满足回答要求",
    ("review", "warning"): "当前证据不足",
    ("replan", "running"): "正在调整查询策略",
    ("generation", "running"): "正在根据证据整理回答",
    ("complete", "completed"): "已完成分析",
}


def phase_text(phase: Phase, status: Status) -> str:
    return PHASE_TEXTS.get((phase, status), "处理中")


def summarize_arguments(tool_name: str, arguments: dict[str, Any]) -> str:
    """把工具参数转成简短中文摘要；禁止输出完整 arguments dict。"""
    parts: list[str] = []
    query = arguments.get("query")
    if isinstance(query, str) and query.strip():
        parts.append(query.strip())
    order_no = arguments.get("order_no")
    if isinstance(order_no, str) and order_no.strip():
        parts.append(f"订单 {order_no.strip()}")
    record_id = arguments.get("record_id")
    if isinstance(record_id, int):
        parts.append(f"文档 {record_id}")
    if tool_name == "commerce.search_association_rules":
        min_lift = arguments.get("min_lift")
        if (
            isinstance(min_lift, (int, float))
            and not isinstance(min_lift, bool)
            and float(min_lift) > 1.0
        ):
            parts.append(f"提升度不低于 {min_lift}")
    return "、".join(parts) if parts else "通用查询"


def tool_evidence_summary(count: int) -> str:
    if count <= 0:
        return "暂未找到有效数据"
    return f"找到 {count} 条可用数据"


def make_counting_sink(inner: ProgressSink | None) -> ProgressSink:
    """包装 sink：为每个事件补 seq（严格递增）与 timestamp（毫秒）。

    在“发送边界”统一编号；多层包装时最外层编号生效（覆盖内层）。
    """

    counter = itertools.count(1)

    async def emit(event: AgentProgressEvent) -> None:
        if inner is None:
            return
        await inner(
            {
                **event,
                "seq": next(counter),
                "timestamp": round(time.time() * 1000, 3),
            }
        )

    return emit


# 属于“Agent 执行”的阶段（持久化摘要只保留这些）。
_EXECUTION_PHASES = {"planning", "tool", "review", "replan"}


def build_execution_summary(events: list[AgentProgressEvent]) -> dict[str, Any] | None:
    """从收集的 progress 事件派生持久化用的精简执行摘要。

    steps 只保留 seq/phase/status/plan/title/detail/tool.label，
    不含 arguments 原文与内部英文工具名；无执行事件时返回 None。
    """
    steps: list[dict[str, Any]] = []
    plan_count = 0
    tool_call_count = 0
    evidence_count = 0
    replan_count = 0
    first_ts: float | None = None
    last_ts: float | None = None
    for event in events:
        phase = event.get("phase")
        if phase not in _EXECUTION_PHASES:
            continue
        status = event.get("status")
        if phase == "planning" and status == "running":
            plan_count += 1
        if phase == "tool" and status == "running":
            tool_call_count += 1
        if phase == "tool" and status == "completed":
            evidence_count += int((event.get("tool") or {}).get("evidenceCount") or 0)
        if phase == "replan":
            replan_count += 1
        ts = event.get("timestamp")
        if isinstance(ts, (int, float)):
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts
        tool = event.get("tool") or {}
        step: dict[str, Any] = {
            "seq": event.get("seq"),
            "phase": phase,
            "status": status,
            "plan": event.get("plan"),
            "title": event.get("title"),
        }
        if event.get("detail") is not None:
            step["detail"] = event["detail"]
        if tool.get("label"):
            step["tool"] = {"label": tool["label"]}
        steps.append(step)
    if not steps:
        return None
    duration_ms = (
        round((last_ts - first_ts) * 1000)
        if first_ts is not None and last_ts is not None
        else 0
    )
    return {
        "summary": {
            "planCount": plan_count,
            "toolCallCount": tool_call_count,
            "evidenceCount": evidence_count,
            "replanCount": replan_count,
            "durationMs": duration_ms,
        },
        "steps": steps,
    }
