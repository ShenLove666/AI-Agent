from __future__ import annotations

import asyncio
from pathlib import Path

from app.modules.rag.agentic import AgenticRagCoordinator
from app.framework.database import Database
from app.framework.migrations import upgrade_database


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
