from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter
from app.modules.commerce.models import Basket, BasketItem, CommerceImport, Product
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest, SearchResult
from app.modules.support.models import SupportCase


TOOLS = frozenset({"knowledge_search", "commerce_data", "support_cases"})


@dataclass(frozen=True, slots=True)
class AgentDecision:
    mode: Literal["direct", "research", "escalate"]
    tools: tuple[str, ...]
    queries: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class AgenticRun:
    decision: AgentDecision
    results: tuple[SearchResult, ...]
    review: str
    steps: tuple[dict[str, Any], ...]


class _State(TypedDict, total=False):
    question: str
    user_id: int
    knowledge_base_ids: tuple[int, ...]
    db: Session
    decision: AgentDecision
    results: list[SearchResult]
    review: str
    attempts: int
    steps: list[dict[str, Any]]


class AgenticRagCoordinator:
    """Bounded ReAct graph: decide -> act -> observe/review -> retry/final."""

    def __init__(self, model_router: ChatModelRouter | None, retrieval: MultiChannelRetrievalEngine | None, *, max_steps: int = 2):
        self.model_router = model_router
        self.retrieval = retrieval
        self.max_steps = max_steps
        graph = StateGraph(_State)
        graph.add_node("planner_agent", self._planner_node)
        graph.add_node("tool_agents", self._tools_node)
        graph.add_node("evidence_agent", self._review_node)
        graph.add_edge(START, "planner_agent")
        graph.add_conditional_edges("planner_agent", self._after_plan, {"act": "tool_agents", "finish": END})
        graph.add_edge("tool_agents", "evidence_agent")
        graph.add_conditional_edges("evidence_agent", self._after_review, {"retry": "tool_agents", "finish": END})
        self.graph = graph.compile()

    async def run(self, db: Session, *, user_id: int, question: str, knowledge_base_ids: tuple[int, ...] = ()) -> AgenticRun:
        state = await self.graph.ainvoke({
            "question": question, "user_id": user_id, "knowledge_base_ids": knowledge_base_ids,
            "db": db, "results": [], "attempts": 0, "steps": [],
        })
        return AgenticRun(state["decision"], tuple(state.get("results", [])), state.get("review", "not_required"), tuple(state.get("steps", [])))

    @staticmethod
    def _fallback_decision(question: str) -> AgentDecision:
        lowered = question.lower()
        if any(term in lowered for term in ("你好", "谢谢", "你是谁", "hello")):
            return AgentDecision("direct", (), (), "普通对话无需调用业务工具")
        tools: list[str] = []
        if any(term in lowered for term in ("购物篮", "订单", "商品", "销量", "关联", "搭配", "取消", "价格", "交易")):
            tools.append("commerce_data")
        if any(term in lowered for term in ("客服", "工单", "案例", "转人工", "质量", "客诉", "咨询")):
            tools.append("support_cases")
        if any(term in lowered for term in ("规则", "政策", "退货", "退款", "售后", "流程", "依据", "法规", "活动")) or not tools:
            tools.append("knowledge_search")
        return AgentDecision("research", tuple(dict.fromkeys(tools)), (question,), "离线规则路由选择了与问题相关的工具")

    async def _decide(self, question: str) -> AgentDecision:
        if self.model_router is None:
            return self._fallback_decision(question)
        prompt = ChatRequest(messages=[
            ChatMessage("system", """你是零售运营 ReAct 规划 Agent。只返回 JSON，不回答问题。可用工具：
knowledge_search：政策、SOP、活动口径；commerce_data：真实购物篮/交易统计；support_cases：客服案例和质量运营。
自主判断 direct/research/escalate，可同时选择多个工具。禁止虚构工具。格式：
{"mode":"research","tools":["knowledge_search"],"queries":["精确检索词"],"rationale":"不超过40字的决策摘要"}"""),
            ChatMessage("user", question),
        ], temperature=0, max_tokens=240, metadata={"agent_role": "planner"})
        try:
            raw = (await self.model_router.complete(prompt)).strip().strip("`")
            if raw.startswith("json"): raw = raw[4:].lstrip()
            value = json.loads(raw)
            mode = value.get("mode")
            tools = tuple(item for item in value.get("tools", []) if item in TOOLS)
            queries = tuple(str(item).strip() for item in value.get("queries", []) if str(item).strip())[:3]
            if mode not in {"direct", "research", "escalate"} or (mode == "research" and not tools):
                raise ValueError("invalid plan")
            return AgentDecision(mode, tools, queries or (question,), str(value.get("rationale", "模型自主路由"))[:120])
        except Exception:
            return self._fallback_decision(question)

    async def _planner_node(self, state: _State) -> dict:
        decision = await self._decide(state["question"])
        return {"decision": decision, "steps": [*state.get("steps", []), {"agent": "planner", "mode": decision.mode, "tools": list(decision.tools), "rationale": decision.rationale}]}

    @staticmethod
    def _after_plan(state: _State) -> str:
        return "act" if state["decision"].mode == "research" else "finish"

    async def _tools_node(self, state: _State) -> dict:
        results: list[SearchResult] = []
        decision = state["decision"]
        query = decision.queries[min(state.get("attempts", 0), len(decision.queries) - 1)]
        for tool in decision.tools:
            if tool == "knowledge_search" and self.retrieval is not None:
                response = await self.retrieval.retrieve(RetrievalRequest(
                    query=query, knowledge_base_ids=tuple(str(item) for item in state.get("knowledge_base_ids", ())),
                    candidate_limit=20, context_limit=6, metadata={"user_id": state["user_id"]},
                ))
                results.extend(response.results)
            elif tool == "commerce_data":
                results.extend(self._commerce_tool(state["db"], state["user_id"]))
            elif tool == "support_cases":
                results.extend(self._support_tool(state["db"], state["user_id"]))
        attempts = state.get("attempts", 0) + 1
        return {"results": results, "attempts": attempts, "steps": [*state.get("steps", []), {"agent": "tools", "attempt": attempts, "tools": list(decision.tools), "observations": len(results)}]}

    @staticmethod
    def _commerce_tool(db: Session, owner_id: int) -> list[SearchResult]:
        latest = db.scalar(select(CommerceImport).where(CommerceImport.owner_id == owner_id).order_by(CommerceImport.id.desc()))
        if latest is None: return []
        baskets = int(db.scalar(select(func.count()).select_from(Basket).where(Basket.import_id == latest.id)) or 0)
        lines = int(db.scalar(select(func.count()).select_from(BasketItem).join(Basket).where(Basket.import_id == latest.id)) or 0)
        products = int(db.scalar(select(func.count()).select_from(Product).where(Product.owner_id == owner_id)) or 0)
        quality = json.loads(latest.quality_report_json or "{}")
        content = f"交易数据源 {latest.source_key}：{baskets} 个订单/购物篮，{lines} 条商品明细，当前商家共 {products} 个来源商品。限制：{'；'.join(quality.get('limitations', []))}"
        return [SearchResult(f"commerce:{latest.id}", content, 1.0, "commerce_data", latest.source_key, {"provenance": "observed+derived", "import_id": latest.id, "source_version": latest.fingerprint[:12]})]

    @staticmethod
    def _support_tool(db: Session, owner_id: int) -> list[SearchResult]:
        groups = db.execute(select(SupportCase.status, SupportCase.priority, func.count()).where(SupportCase.owner_id == owner_id).group_by(SupportCase.status, SupportCase.priority)).all()
        if not groups: return []
        summary = "，".join(f"{status}/{priority}={count}" for status, priority, count in groups)
        return [SearchResult("support:coverage", f"客服案例覆盖：{summary}。这些案例为演示生成案例，不能当作真实顾客对话。", 1.0, "support_cases", "support_cases", {"provenance": "synthetic", "groups": len(groups)})]

    async def _review_node(self, state: _State) -> dict:
        results = state.get("results", [])
        if results:
            review = "ready: 已获得带来源标记的工具证据"
        elif state.get("attempts", 0) < self.max_steps:
            review = "retry: 首轮无证据，执行一次受限重试"
        else:
            review = "escalate: 达到步数上限仍无可靠证据"
        return {"review": review, "steps": [*state.get("steps", []), {"agent": "evidence_reviewer", "review": review, "evidence": len(results)}]}

    def _after_review(self, state: _State) -> str:
        return "retry" if state.get("review", "").startswith("retry") and state.get("attempts", 0) < self.max_steps else "finish"
