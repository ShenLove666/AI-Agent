"""Agent 执行进度事件：事件结构、中文展示映射与进度收集工具。

所有面向用户的文本（title/detail/argumentsSummary/tool label）的中文映射
以本模块为唯一权威来源；节点与 service 禁止直接向用户透出内部英文工具名、
Planner rationale 或工具参数的完整 JSON 原文。

build_execution_summary 采用 reducer 语义：同一逻辑步骤（合并键
(plan, phase, callId 或 toolKey)）的多个事件合并为最终一条，与前端 live
合并语义一致，确保实时展示与历史 restore 看到的步骤一致。同 Plan 内同一工具
的重复调用（不同 callId）保留为独立步骤，running→completed（同 callId）仍合并。
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
    callId: str
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
    ("rewrite", "running"): "正在理解问题",
    ("rewrite", "completed"): "问题理解完成",
    ("planning", "running"): "正在制定查询计划",
    ("planning", "completed"): "查询计划已制定",
    ("tool", "running"): "正在查询数据",
    ("tool", "completed"): "查询完成",
    ("review", "running"): "正在核验证据",
    ("review", "completed"): "证据已满足回答要求",
    ("review", "warning"): "当前证据不足",
    ("replan", "running"): "正在调整查询策略",
    ("replan", "completed"): "已调整查询策略",
    ("generation", "running"): "正在根据证据整理回答",
    ("generation", "completed"): "回答生成完成",
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


# 属于“Agent 执行”的阶段（持久化摘要只保留这些；complete 排除）。
_EXECUTION_PHASES = {"planning", "tool", "review", "replan", "generation"}


def _event_tool_key(event: AgentProgressEvent) -> str | None:
    """派生稳定且不敏感的 toolKey（commerce.search_association_rules →
    commerce_search_association_rules）；无工具名时返回 None。"""
    name = (event.get("tool") or {}).get("name")
    if not name:
        return None
    return str(name).replace(".", "_")


def build_execution_summary(
    events: list[AgentProgressEvent], final_status: str | None = None
) -> dict[str, Any] | None:
    """从收集的 progress 事件派生持久化用的精简执行摘要（reducer 语义）。

    同一逻辑步骤（合并键 (plan, phase, callId 或 toolKey)，callId 取自事件
    tool.callId）的多个事件合并为最终一条：同 Plan 内同一工具重复调用（不同
    callId）保留为独立步骤，同 callId 的 running→completed 仍合并为一条；
    后续事件覆盖 status/title/detail/tool（保留最新 evidenceCount/durationMs，
    只保留工具最后状态）；step["seq"] 保留该 key 首个事件的 seq。
    steps 只保留 seq/phase/status/plan/title/detail/tool.label/toolKey/callId/
    evidenceCount/durationMs，不含 arguments 原文、rationale 与内部英文工具名；
    final_status 提供时（"failed"/"cancelled"）把合并后仍为 running 的步骤
    强制改为该状态。无执行事件时返回 None。
    summary 额外捕获 phase=="complete" 且带 "terminal" 字段的事件写入
    terminalState（direct/grounded/refused/escalated；缺省不写），带
    "intent" 字段的事件写入 intent（direct/history_reference/research/
    refuse；缺省不写）。
    """
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    order: list[tuple[Any, Any, Any]] = []
    first_ts: float | None = None
    last_ts: float | None = None
    # 终态来自 phase=="complete" 且带 "terminal" 的事件（complete 阶段本身
    # 不进 steps，只用于向 summary 写入 terminalState；无该字段时不写）。
    terminal_state: str | None = None
    # 意图路由结果来自 phase=="complete" 且带 "intent" 的事件（缺省不写）。
    intent: str | None = None
    for event in events:
        phase = event.get("phase")
        if phase == "complete" and event.get("terminal"):
            terminal_state = str(event["terminal"])
        if phase == "complete" and event.get("intent"):
            intent = str(event["intent"])
        if phase not in _EXECUTION_PHASES:
            continue
        tool = event.get("tool") or {}
        tool_key = _event_tool_key(event)
        call_id = tool.get("callId")
        key = (event.get("plan"), phase, call_id if call_id is not None else tool_key)
        ts = event.get("timestamp")
        if isinstance(ts, (int, float)):
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts
        if key not in merged:
            merged[key] = {
                "seq": event.get("seq"),
                "phase": phase,
                "status": event.get("status"),
                "plan": event.get("plan"),
                "title": event.get("title"),
            }
            if tool_key is not None:
                merged[key]["tool"] = {"label": tool.get("label"), "toolKey": tool_key}
                if call_id is not None:
                    merged[key]["tool"]["callId"] = call_id
            order.append(key)
        step = merged[key]
        # 后续事件覆盖 status/title/detail/tool；无 detail 的新事件清掉旧 detail
        step["status"] = event.get("status")
        step["title"] = event.get("title")
        if event.get("detail") is not None:
            step["detail"] = event["detail"]
        else:
            step.pop("detail", None)
        if tool_key is not None:
            tool_step = step.setdefault(
                "tool", {"label": tool.get("label"), "toolKey": tool_key}
            )
            tool_step["label"] = tool.get("label")
            tool_step["toolKey"] = tool_key
            if call_id is not None:
                tool_step["callId"] = call_id
            if tool.get("evidenceCount") is not None:
                tool_step["evidenceCount"] = tool["evidenceCount"]
            if tool.get("durationMs") is not None:
                tool_step["durationMs"] = tool["durationMs"]
    if not merged:
        return None
    steps: list[dict[str, Any]] = []
    for key in order:
        step = merged[key]
        if final_status is not None and step.get("status") == "running":
            step["status"] = final_status
        steps.append(step)
    plan_count = max(
        (step["plan"] for step in steps if step.get("plan") is not None), default=1
    )
    tool_call_count = sum(
        1
        for step in steps
        if step["phase"] == "tool" and step.get("status") in {"completed", "failed"}
    )
    evidence_count = sum(
        int((step.get("tool") or {}).get("evidenceCount") or 0)
        for step in steps
        if step["phase"] == "tool" and step.get("status") == "completed"
    )
    replan_count = sum(1 for step in steps if step["phase"] == "replan")
    duration_ms = (
        last_ts - first_ts if first_ts is not None and last_ts is not None else 0
    )
    summary: dict[str, Any] = {
        "planCount": plan_count,
        "toolCallCount": tool_call_count,
        "evidenceCount": evidence_count,
        "replanCount": replan_count,
        "durationMs": duration_ms,
    }
    if terminal_state is not None:
        summary["terminalState"] = terminal_state
    if intent is not None:
        summary["intent"] = intent
    return {
        "summary": summary,
        "steps": steps,
    }
