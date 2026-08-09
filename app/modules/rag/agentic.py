from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Required, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter
from app.modules.rag.agent_tools import ToolContext, ToolRegistry, build_tool_registry
from app.modules.rag.progress import (
    AgentProgressEvent,
    ProgressSink,
    make_counting_sink,
    phase_text,
    summarize_arguments,
    tool_evidence_summary,
    tool_label,
)
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import SearchResult


_LEGACY_NAMES = {
    "knowledge.search": "knowledge_search",
    "commerce.search_association_rules": "commerce_data",
    "commerce.get_product_metrics": "commerce_data",
    "support.search_cases": "support_cases",
    "support.get_quality_metrics": "support_cases",
    "support.get_knowledge_gaps": "support_cases",
}


def _join_chinese(items: list[str]) -> str:
    """中文列举：['A'] -> 'A'；['A','B'] -> 'A和B'；更多 -> 'A、B和C'。"""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return "、".join(items[:-1]) + "和" + items[-1]


class ToolCallPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["direct", "research", "escalate", "refuse"]
    calls: tuple[ToolCallPlan, ...] = ()
    rationale: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_calls(self):
        if self.mode == "research" and not self.calls:
            raise ValueError("research plan requires tool calls")
        if self.mode != "research" and self.calls:
            raise ValueError("terminal plan cannot call tools")
        return self


@dataclass(frozen=True, slots=True)
class AgentDecision:
    mode: Literal["direct", "research", "escalate", "refuse"]
    calls: tuple[ToolCallPlan, ...]
    rationale: str
    runtime_mode: Literal["deterministic_fallback", "model_backed", "risk_guard"]

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                _LEGACY_NAMES.get(call.name, call.name) for call in self.calls
            )
        )

    @property
    def queries(self) -> tuple[str, ...]:
        return tuple(
            str(call.arguments.get("query", "")).strip()
            for call in self.calls
            if str(call.arguments.get("query", "")).strip()
        )


class EvidenceReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: str
    relevance: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    conflicts: tuple[str, ...] = ()
    authority_sufficient: bool
    missing_fields: tuple[str, ...] = ()
    risk: Literal["low", "medium", "high"]
    decision: Literal["ready", "replan", "escalate", "refuse"]
    summary: str


@dataclass(frozen=True, slots=True)
class AgenticRun:
    decision: AgentDecision
    results: tuple[SearchResult, ...]
    review: str
    review_details: EvidenceReview
    steps: tuple[dict[str, Any], ...]
    terminal_state: Literal["direct", "grounded", "refused", "escalated"]
    runtime_mode: Literal["deterministic_fallback", "model_backed", "risk_guard"]

    @property
    def answer(self) -> str:
        if self.terminal_state == "direct":
            return "您好，我可以协助查询商家政策、零售数据和客服运营问题。"
        if self.terminal_state in {"refused", "escalated"} or not self.results:
            return "当前证据不足，无法给出可靠结论，建议转人工复核。"
        excerpts = [" ".join(item.content.split())[:240] for item in self.results[:3]]
        return "根据已检索到的来源证据：" + "；".join(excerpts)


class _State(TypedDict, total=False):
    # run() 初始状态保证以下 key 恒存在，允许安全下标访问
    question: Required[str]
    user_id: Required[int]
    knowledge_base_ids: Required[tuple[int, ...]]
    db: Required[Session]
    results: Required[list[SearchResult]]
    plan_count: Required[int]
    tool_calls: Required[int]
    plan_history: Required[list[dict[str, Any]]]
    tool_errors: Required[list[dict[str, Any]]]
    steps: Required[list[dict[str, Any]]]
    review_feedback: Required[str]
    # planner 节点首轮写入，访问点需 .get() + 断言收窄
    decision: AgentDecision
    # 图节点中途写入的 key
    initial_decision: AgentDecision
    review: str
    review_details: EvidenceReview
    terminal_state: Literal["direct", "grounded", "refused", "escalated"]


class AgenticRagCoordinator:
    """Bounded planner -> typed tools -> evidence review -> re-planner graph."""

    def __init__(
        self,
        model_router: ChatModelRouter | None,
        retrieval: MultiChannelRetrievalEngine | None,
        *,
        max_steps: int = 2,
        max_tool_calls: int = 8,
        registry: ToolRegistry | None = None,
    ):
        self.model_router = model_router
        self.retrieval = retrieval
        self.max_steps = max(1, max_steps)
        self.max_tool_calls = max(1, max_tool_calls)
        self.registry = registry or build_tool_registry(retrieval)
        self.graph = self._compile_graph(None)

    def _compile_graph(self, sink: ProgressSink | None):
        """构造 LangGraph。sink 通过闭包捕获，随 run() 请求级传入，避免实例共享。

        节点函数签名保持 (state) -> dict，sink 由闭包持有，天然支持并发请求。
        """
        emit = make_counting_sink(sink)

        async def planner_node(state: _State) -> dict[str, Any]:
            return await self._planner_node(state, emit)

        async def tools_node(state: _State) -> dict[str, Any]:
            return await self._tools_node(state, emit)

        async def review_node(state: _State) -> dict[str, Any]:
            return await self._review_node(state, emit)

        graph = StateGraph(_State)
        graph.add_node("planner_agent", planner_node)
        graph.add_node("tool_agents", tools_node)
        graph.add_node("evidence_agent", review_node)
        graph.add_edge(START, "planner_agent")
        graph.add_conditional_edges(
            "planner_agent", self._after_plan, {"act": "tool_agents", "finish": END}
        )
        graph.add_edge("tool_agents", "evidence_agent")
        graph.add_conditional_edges(
            "evidence_agent",
            self._after_review,
            {"replan": "planner_agent", "finish": END},
        )
        return graph.compile()

    async def run(
        self,
        db: Session,
        *,
        user_id: int,
        question: str,
        knowledge_base_ids: tuple[int, ...] = (),
        progress_sink: ProgressSink | None = None,
    ) -> AgenticRun:
        state = await self._compile_graph(progress_sink).ainvoke(
            {
                "question": question,
                "user_id": user_id,
                "knowledge_base_ids": knowledge_base_ids,
                "db": db,
                "results": [],
                "plan_count": 0,
                "tool_calls": 0,
                "plan_history": [],
                "tool_errors": [],
                "steps": [],
                "review_feedback": "",
            }
        )
        decision = state.get("initial_decision") or state.get("decision")
        assert decision is not None, "planner must produce a decision"
        terminal: Literal["direct", "grounded", "refused", "escalated"] = state.get(
            "terminal_state"
        ) or self._terminal_for(decision.mode, bool(state.get("results")))
        review_details = state.get("review_details") or EvidenceReview(
            intent="general",
            relevance=1,
            coverage=1,
            authority_sufficient=True,
            risk="low",
            decision="ready",
            summary="无需证据审查",
        )
        return AgenticRun(
            decision,
            tuple(state.get("results", [])),
            state.get("review", "not_required"),
            review_details,
            tuple(state.get("steps", [])),
            terminal,
            decision.runtime_mode,
        )

    def _fallback_decision(
        self, question: str, history: list[dict[str, Any]], feedback: str
    ) -> AgentDecision:
        lowered = question.lower()
        if not history and any(
            term in lowered for term in ("你好", "谢谢", "你是谁", "hello")
        ):
            return AgentDecision(
                "direct", (), "普通对话无需调用业务工具", "deterministic_fallback"
            )
        if any(term in lowered for term in ("伪造", "欺骗", "假截图")):
            return AgentDecision(
                "refuse", (), "请求涉及欺骗或伪造", "deterministic_fallback"
            )
        used = {call["name"] for plan in history for call in plan.get("calls", [])}
        order_match = re.search(
            r"订单\s*(?:号|[:：#])?\s*([A-Za-z0-9][A-Za-z0-9_-]{4,79})",
            question,
            re.IGNORECASE,
        )
        if order_match and not history:
            order_no = order_match.group(1)
            order_tools = ["commerce.get_order"]
            if any(
                term in lowered
                for term in ("配送", "送达", "物流", "骑手", "到达", "迟到", "延误")
            ):
                order_tools.append("commerce.get_delivery_status")
            if any(term in lowered for term in ("退款", "退货", "售后", "赔付")):
                order_tools.append("commerce.get_refund_status")
            if any(term in lowered for term in ("顾客", "客户", "历史", "会员")):
                order_tools.append("commerce.get_customer_history")
            calls = tuple(
                ToolCallPlan(name=name, arguments={"order_no": order_no})
                for name in order_tools
            )
            return AgentDecision(
                "research",
                calls,
                "检测到订单号，优先查询订单及问题所需的实时业务事实",
                "deterministic_fallback",
            )
        candidates: list[str] = []
        if any(
            term in lowered
            for term in (
                "购物篮",
                "订单",
                "商品",
                "销量",
                "关联",
                "搭配",
                "取消",
                "价格",
                "交易",
            )
        ):
            candidates.extend(
                ("commerce.search_association_rules", "commerce.get_product_metrics")
            )
        if any(
            term in lowered
            for term in (
                "客服",
                "工单",
                "案例",
                "转人工",
                "质量",
                "客诉",
                "咨询",
                "缺口",
            )
        ):
            candidates.extend(
                (
                    "support.search_cases",
                    "support.get_quality_metrics",
                    "support.get_knowledge_gaps",
                )
            )
        if (
            any(
                term in lowered
                for term in (
                    "规则",
                    "政策",
                    "退货",
                    "退款",
                    "售后",
                    "流程",
                    "依据",
                    "法规",
                    "活动",
                    "安全",
                )
            )
            or not candidates
        ):
            candidates.append("knowledge.search")
        if history:
            alternatives = [
                name
                for name in (*candidates, "knowledge.search", "support.search_cases")
                if name not in used
            ]
            if not alternatives:
                return AgentDecision(
                    "escalate",
                    (),
                    "重新规划后仍无可用的新证据路径",
                    "deterministic_fallback",
                )
            candidates = alternatives[:2]
        calls = tuple(
            ToolCallPlan(name=name, arguments={"query": question, "limit": 6})
            for name in dict.fromkeys(candidates)
            if self.registry.canonical_name(name)
        )
        return AgentDecision(
            "research",
            calls,
            "离线规划器根据问题与上一轮反馈选择业务工具"
            + (f"：{feedback[:60]}" if feedback else ""),
            "deterministic_fallback",
        )

    async def _decide(self, state: _State) -> AgentDecision:
        question = state["question"]
        history = state.get("plan_history", [])
        feedback = state.get("review_feedback", "")
        if self.model_router is None:
            return self._fallback_decision(question, history, feedback)
        tool_text = json.dumps(self.registry.describe(), ensure_ascii=False)
        prior = json.dumps(
            {
                "plans": history[-2:],
                "feedback": feedback,
                "errors": state.get("tool_errors", [])[-4:],
            },
            ensure_ascii=False,
        )
        prompt = ChatRequest(
            messages=[
                ChatMessage(
                    "system",
                    '你是零售运营规划 Agent。只返回 JSON：{"mode":"research|direct|refuse|escalate","calls":[{"name":"工具名","arguments":{}}],"rationale":"摘要"}。证据不足重规划时必须改变工具或参数，否则结束。当上一轮工具成功但返回 0 条结果时，重新规划必须扩大召回、修改实体表达、降低合理过滤条件或更换数据源；禁止仅通过提高 min_lift、min_confidence、threshold 等过滤条件重复调用同一工具。可用工具：'
                    + tool_text,
                ),
                ChatMessage("user", f"问题：{question}\n先前状态：{prior}"),
            ],
            temperature=0,
            max_tokens=500,
            metadata={"agent_role": "planner"},
        )
        try:
            raw = (await self.model_router.complete(prompt)).strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
            value = json.loads(raw)
            if "tools" in value and "calls" not in value:
                queries = value.pop("queries", [question]) or [question]
                value["calls"] = [
                    {
                        "name": name,
                        "arguments": {
                            "query": queries[min(index, len(queries) - 1)],
                            "limit": 6,
                        },
                    }
                    for index, name in enumerate(value.pop("tools", []))
                ]
            payload = PlanPayload.model_validate(value)
            calls = tuple(
                ToolCallPlan(
                    name=self.registry.canonical_name(call.name) or "",
                    arguments=call.arguments,
                )
                for call in payload.calls
            )
            if any(not call.name for call in calls):
                raise ValueError("unknown tool")
            return AgentDecision(
                payload.mode, calls, payload.rationale or "模型规划", "model_backed"
            )
        except Exception:
            return self._fallback_decision(question, history, feedback)

    async def _planner_node(
        self, state: _State, sink: ProgressSink
    ) -> dict[str, Any]:
        count = state.get("plan_count", 0) + 1
        await sink(
            {
                "phase": "planning",
                "status": "running",
                "agent": "planner",
                "plan": count,
                "title": phase_text("planning", "running"),
                "detail": "正在判断需要查询哪些业务数据",
            }
        )
        decision = await self._decide(state)
        # Risk Guard：高风险/中风险问题不允许 direct 直答，防止绕过证据审查门禁
        if decision.mode == "direct":
            question = state.get("question", "")
            _, _, risk = self._intent_requirements(question)
            if risk in {"medium", "high"}:
                fallback = self._fallback_decision(
                    question,
                    state.get("plan_history", []),
                    "风险门禁：高风险问题禁止直答，强制查证",
                )
                if fallback.mode == "research":
                    decision = AgentDecision(
                        "research",
                        fallback.calls,
                        f"风险门禁拦截 direct：{fallback.rationale}",
                        "risk_guard",
                    )
                else:
                    decision = AgentDecision(
                        "escalate",
                        (),
                        "风险门禁：高风险问题且无可用的查证路径，转人工",
                        "risk_guard",
                    )
        if decision.mode == "research":
            labels = [tool_label(call.name) for call in decision.calls]
            plan_detail = "准备查询" + _join_chinese(labels)
        else:
            plan_detail = {
                "direct": "可直接回答",
                "refuse": "拒绝回答",
                "escalate": "转人工复核",
            }[decision.mode]
        await sink(
            {
                "phase": "planning",
                "status": "completed",
                "agent": "planner",
                "plan": count,
                "title": phase_text("planning", "completed"),
                "detail": plan_detail,
            }
        )
        history = [
            *state.get("plan_history", []),
            {
                "mode": decision.mode,
                "calls": [call.model_dump() for call in decision.calls],
                "rationale": decision.rationale,
            },
        ]
        update: dict[str, Any] = {
            "decision": decision,
            "plan_count": count,
            "plan_history": history,
            "steps": [
                *state.get("steps", []),
                {
                    "agent": "planner",
                    "plan": count,
                    "mode": decision.mode,
                    "tools": list(decision.tools),
                    "calls": [call.model_dump() for call in decision.calls],
                    "rationale": decision.rationale,
                    "runtimeMode": decision.runtime_mode,
                },
            ],
        }
        if "initial_decision" not in state:
            update["initial_decision"] = decision
        if decision.mode != "research":
            update["terminal_state"] = self._terminal_for(decision.mode, False)
        return update

    @staticmethod
    def _after_plan(state: _State) -> str:
        decision = state.get("decision")
        return (
            "act" if decision is not None and decision.mode == "research" else "finish"
        )

    async def _tools_node(self, state: _State, sink: ProgressSink) -> dict[str, Any]:
        results = list(state.get("results", []))
        errors = list(state.get("tool_errors", []))
        executions: list[dict[str, Any]] = []
        used = state.get("tool_calls", 0)
        decision = state.get("decision")
        plan = state.get("plan_count", 1)
        context = ToolContext(
            state["db"], state["user_id"], state.get("knowledge_base_ids", ())
        )
        for call in decision.calls if decision is not None else ():
            if used >= self.max_tool_calls:
                errors.append({"tool": call.name, "code": "TOOL_BUDGET_EXCEEDED"})
                break
            label = tool_label(call.name)
            arguments_summary = summarize_arguments(call.name, call.arguments)
            await sink(
                {
                    "phase": "tool",
                    "status": "running",
                    "agent": "tools",
                    "plan": plan,
                    "title": label,
                    "detail": arguments_summary,
                    "tool": {
                        "name": call.name,
                        "label": label,
                        "status": "running",
                        "argumentsSummary": arguments_summary,
                    },
                }
            )
            outcome = await self.registry.execute(call.name, call.arguments, context)
            used += 1
            executions.append(outcome.model_dump(exclude={"evidence"}))
            results.extend(
                item.as_search_result(outcome.tool) for item in outcome.evidence
            )
            if outcome.error_code:
                errors.append({"tool": outcome.tool, "code": outcome.error_code})
            evidence_count = len(outcome.evidence)
            if outcome.status == "success":
                status: Literal["completed", "failed"] = "completed"
                detail = tool_evidence_summary(evidence_count)
            else:
                status = "failed"
                detail = "查询失败，已跳过该数据源"
            await sink(
                {
                    "phase": "tool",
                    "status": status,
                    "agent": "tools",
                    "plan": plan,
                    "title": label,
                    "detail": detail,
                    "tool": {
                        "name": call.name,
                        "label": label,
                        "status": status,
                        "durationMs": outcome.duration_ms,
                        "evidenceCount": evidence_count,
                    },
                }
            )
        return {
            "results": results,
            "tool_calls": used,
            "tool_errors": errors,
            "steps": [
                *state.get("steps", []),
                {
                    "agent": "tools",
                    "plan": state.get("plan_count", 1),
                    "executions": executions,
                    "observations": len(results),
                    "toolCalls": used,
                },
            ],
        }

    async def _review_node(self, state: _State, sink: ProgressSink) -> dict[str, Any]:
        results = state.get("results", [])
        can_replan = (
            state.get("plan_count", 0) < self.max_steps
            and state.get("tool_calls", 0) < self.max_tool_calls
        )
        plan = state.get("plan_count", 1)
        await sink(
            {
                "phase": "review",
                "status": "running",
                "agent": "evidence_reviewer",
                "plan": plan,
                "title": phase_text("review", "running"),
                "detail": "正在核对已获取的证据是否满足回答要求",
            }
        )
        details = self._review_evidence(state["question"], results, can_replan)
        prefix = "retry" if details.decision == "replan" else details.decision
        review = f"{prefix}: {details.summary}"
        terminal = {
            "ready": "grounded",
            "replan": "",
            "escalate": "escalated",
            "refuse": "refused",
        }[details.decision]
        review_metrics: dict[str, Any] = {
            "evidenceCount": len(results),
            "coverage": details.coverage,
            "conflictCount": len(details.conflicts),
        }
        if details.decision == "ready":
            await sink(
                {
                    "phase": "review",
                    "status": "completed",
                    "agent": "evidence_reviewer",
                    "plan": plan,
                    "title": phase_text("review", "completed"),
                    "detail": f"已核验 {len(results)} 条证据",
                    "metrics": review_metrics,
                }
            )
        elif details.decision == "replan":
            await sink(
                {
                    "phase": "review",
                    "status": "warning",
                    "agent": "evidence_reviewer",
                    "plan": plan,
                    "title": "当前证据不足",
                    "detail": "正在补充查询",
                    "metrics": review_metrics,
                }
            )
            await sink(
                {
                    "phase": "replan",
                    "status": "running",
                    "agent": "evidence_reviewer",
                    "plan": plan + 1,
                    "title": phase_text("replan", "running"),
                    "detail": "首次查询信息不足，正在尝试新的数据来源",
                }
            )
        elif details.decision == "escalate":
            await sink(
                {
                    "phase": "review",
                    "status": "warning",
                    "agent": "evidence_reviewer",
                    "plan": plan,
                    "title": "现有证据不足以形成可靠结论",
                    "detail": details.summary,
                    "metrics": review_metrics,
                }
            )
        else:
            await sink(
                {
                    "phase": "review",
                    "status": "completed",
                    "agent": "evidence_reviewer",
                    "plan": plan,
                    "title": "已确认拒绝回答",
                    "detail": details.summary,
                    "metrics": review_metrics,
                }
            )
        return {
            "review": review,
            "review_details": details,
            "review_feedback": review,
            "terminal_state": terminal,
            "steps": [
                *state.get("steps", []),
                {
                    "agent": "evidence_reviewer",
                    "review": review,
                    "details": details.model_dump(),
                    "evidence": len(results),
                    "plan": state.get("plan_count", 1),
                },
            ],
        }

    @classmethod
    def _review_evidence(
        cls,
        question: str,
        results: list[SearchResult],
        can_replan: bool,
    ) -> EvidenceReview:
        intent, required, risk = cls._intent_requirements(question)
        present = {cls._fact_type(item) for item in results}
        present.discard(None)
        missing = tuple(sorted(required - present))
        coverage = (
            len(required & present) / len(required)
            if required
            else (1.0 if results else 0.0)
        )
        relevance = coverage if required else (1.0 if results else 0.0)
        conflicts = cls._find_conflicts(results)
        authority_sufficient = risk != "high" or any(
            cls._fact_type(item) == "policy"
            and bool(item.metadata.get("publisher"))
            and item.metadata.get("review_status") == "current"
            for item in results
        )

        if not results:
            decision = "replan" if can_replan else "escalate"
            summary = "当前计划没有获得可用证据"
        elif conflicts:
            decision = "escalate"
            summary = "关键证据相互冲突，需要人工确认权威版本"
        elif missing:
            decision = "replan" if can_replan else "escalate"
            summary = "证据未覆盖回答所需字段：" + "、".join(missing)
        elif not authority_sufficient:
            decision = "escalate"
            summary = "高风险结论缺少当前有效且可归属的权威来源"
        else:
            decision = "ready"
            summary = "证据相关、覆盖完整且满足风险要求"

        return EvidenceReview(
            intent=intent,
            relevance=round(relevance, 4),
            coverage=round(coverage, 4),
            conflicts=conflicts,
            authority_sufficient=authority_sufficient,
            missing_fields=missing,
            risk=risk,
            decision=decision,
            summary=summary,
        )

    @staticmethod
    def _intent_requirements(
        question: str,
    ) -> tuple[str, set[str], Literal["low", "medium", "high"]]:
        lowered = question.lower()
        has_order = bool(
            re.search(
                r"订单\s*(?:号|[:：#])?\s*[A-Za-z0-9][A-Za-z0-9_-]{4,79}",
                question,
                re.IGNORECASE,
            )
        )
        if any(
            term in lowered for term in ("送达", "配送", "物流", "骑手", "延误", "迟到")
        ):
            return "delivery_status", {"order", "delivery"}, "medium"
        # 商业分析：优先级高于 policy_lookup。含高优先级政策风险词
        # （退款/退货/食品安全/支付安全等）时让位给政策/售后分支。
        if any(
            term in lowered
            for term in (
                "商品", "销量", "搭配", "关联", "共现", "购物篮", "经营",
                "销售", "推荐", "提升度", "支持度", "置信度",
                "购买组合", "商品组合", "销售数据", "卖得",
            )
        ) and not any(
            term in lowered
            for term in (
                "退款", "退货", "七日无理由", "赔付", "食品安全", "变质",
                "还能吃", "还能喝", "不冰", "扣款", "支付", "验证码", "账号安全",
            )
        ):
            required: set[str] = set()
            if any(
                term in lowered
                for term in (
                    "搭配", "关联", "共现", "购物篮", "提升度", "支持度",
                    "置信度", "购买组合", "商品组合",
                )
            ):
                required.add("association_rule")
            if any(
                term in lowered
                for term in ("销量", "经营", "销售", "卖得", "销售数据")
            ):
                required.add("product_metrics")
            if not required:
                required = {"association_rule", "product_metrics"}
            return "commerce_analysis", required, "low"
        # 政策检索：必须有明确政策框架词才触发；单独的「依据」不触发。
        if any(
            term in lowered
            for term in (
                "政策", "规则", "法规", "平台规定", "售后规定",
                "法律依据", "监管要求", "官方规定",
            )
        ):
            return "policy_lookup", {"policy"}, "medium"
        if any(term in lowered for term in ("退款", "退货", "七日无理由", "赔付")):
            required = {"policy"}
            if has_order:
                required.update(("order", "refund"))
            return "refund_policy", required, "high"
        if any(
            term in lowered for term in ("食品安全", "变质", "还能吃", "还能喝", "不冰")
        ):
            required = {"policy"}
            if has_order:
                required.add("order")
            return "food_safety", required, "high"
        if any(term in lowered for term in ("扣款", "支付", "验证码", "账号安全")):
            return "account_or_payment_risk", {"policy"}, "high"
        return "general", set(), "low"

    @staticmethod
    def _fact_type(item: SearchResult) -> str | None:
        explicit = item.metadata.get("factType") or item.metadata.get("fact_type")
        if explicit:
            return str(explicit)
        channel = item.channel
        if channel == "commerce.get_order":
            return "order"
        if channel == "commerce.get_delivery_status":
            return "delivery"
        if channel == "commerce.get_refund_status":
            return "refund"
        if channel == "commerce.get_customer_history":
            return "customer_history"
        if channel.startswith("knowledge") or item.metadata.get("document_id"):
            return "policy"
        return None

    @staticmethod
    def _find_conflicts(results: list[SearchResult]) -> tuple[str, ...]:
        claims: dict[str, set[str]] = {}
        for item in results:
            key = item.metadata.get("claimKey")
            value = item.metadata.get("claimValue")
            if key is not None and value is not None:
                claims.setdefault(str(key), set()).add(str(value))
        return tuple(
            f"{key}: {' <> '.join(sorted(values))}"
            for key, values in sorted(claims.items())
            if len(values) > 1
        )

    @staticmethod
    def _after_review(state: _State) -> str:
        return "replan" if state.get("review", "").startswith("retry") else "finish"

    @staticmethod
    def _terminal_for(
        mode: str, has_results: bool
    ) -> Literal["direct", "grounded", "refused", "escalated"]:
        if mode == "direct":
            return "direct"
        if mode == "refuse":
            return "refused"
        if mode == "escalate" or not has_results:
            return "escalated"
        return "grounded"
