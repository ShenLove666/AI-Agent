from __future__ import annotations

import asyncio
from pathlib import Path

from app.modules.rag.agentic import AgenticRagCoordinator
from app.framework.database import Database
from app.framework.migrations import upgrade_database


class _PlanningRouter:
    def __init__(self):
        self.calls = 0

    async def complete(self, _request):
        self.calls += 1
        if self.calls == 1:
            return '{"mode":"research","calls":[{"name":"commerce.get_product_metrics","arguments":{"query":"不存在商品"}}],"rationale":"先查商品"}'
        return '{"mode":"research","calls":[{"name":"knowledge.search","arguments":{"query":"不存在规则"}}],"rationale":"改查知识"}'


def test_react_agent_autonomously_selects_tools_and_direct_mode(tmp_path: Path):
    async def scenario():
        coordinator = AgenticRagCoordinator(None, None)
        database = Database(f"sqlite:///{tmp_path / 'agentic.db'}")
        upgrade_database(database)
        with database.session_factory() as db:
            direct = await coordinator.run(db, user_id=1, question="你好")
            assert direct.decision.mode == "direct" and not direct.decision.tools
            research = await coordinator.run(db, user_id=1, question="分析购物篮，并结合退货政策说明风险")
            assert set(research.decision.tools) == {"commerce_data", "knowledge_search"}
            assert research.steps[0]["agent"] == "planner"
            assert research.steps[-1]["agent"] == "evidence_reviewer"
            assert len([step for step in research.steps if step["agent"] == "tools"]) == 2
            assert research.review.startswith("escalate")
    asyncio.run(scenario())


def test_insufficient_evidence_returns_to_planner_with_changed_strategy(tmp_path: Path):
    async def scenario():
        router = _PlanningRouter()
        coordinator = AgenticRagCoordinator(router, None, max_steps=2, max_tool_calls=3)
        database = Database(f"sqlite:///{tmp_path / 'replan.db'}")
        upgrade_database(database)
        with database.session_factory() as db:
            result = await coordinator.run(db, user_id=1, question="查询不存在的商品和规则")
            planner_steps = [step for step in result.steps if step["agent"] == "planner"]
            assert router.calls == 2 and len(planner_steps) == 2
            assert planner_steps[0]["calls"] != planner_steps[1]["calls"]
            assert result.terminal_state == "escalated"
            assert len([step for step in result.steps if step["agent"] == "tools"]) == 2
            assert result.runtime_mode == "model_backed"

    asyncio.run(scenario())


def test_malformed_model_plan_uses_typed_deterministic_fallback(tmp_path: Path):
    class BrokenRouter:
        async def complete(self, _request):
            return "not-json"

    async def scenario():
        coordinator = AgenticRagCoordinator(BrokenRouter(), None, max_steps=1)
        database = Database(f"sqlite:///{tmp_path / 'fallback.db'}")
        upgrade_database(database)
        with database.session_factory() as db:
            result = await coordinator.run(db, user_id=1, question="退货政策是什么")
            assert result.runtime_mode == "deterministic_fallback"
            assert result.steps[0]["calls"][0]["name"] == "knowledge.search"
            assert result.terminal_state == "escalated"

    asyncio.run(scenario())
