from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.modules.rag.agent_tools import AgentTool, ToolEvidence, ToolRegistry
from app.modules.rag.agentic import AgenticRagCoordinator


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)


class _FixedPlanner:
    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    async def complete(self, _request):
        return (
            '{"mode":"research","calls":[{"name":"'
            + self.tool_name
            + '","arguments":{"query":"case"}}],"rationale":"test plan"}'
        )


def test_policy_text_without_live_order_facts_is_not_ready(tmp_path):
    async def policy_handler(_context, _value):
        return [
            ToolEvidence(
                id="policy:delivery",
                content="配送延误时应主动告知顾客。",
                source="delivery-policy",
                provenance="public_summary",
                metadata={"factType": "policy", "review_status": "current"},
            )
        ]

    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'insufficient-review.db'}")
        Base.metadata.create_all(database.engine)
        registry = ToolRegistry(
            [AgentTool("test.policy", "policy", _Query, policy_handler)]
        )
        coordinator = AgenticRagCoordinator(
            _FixedPlanner("test.policy"),
            None,
            max_steps=1,
            registry=registry,
        )
        with database.session_factory() as db:
            result = await coordinator.run(
                db,
                user_id=1,
                question="订单 NB-REVIEW-001 什么时候送达？",
            )

        assert result.terminal_state == "escalated"
        assert result.review_details.decision == "escalate"
        assert result.review_details.intent == "delivery_status"
        assert set(result.review_details.missing_fields) == {"order", "delivery"}
        assert result.review_details.coverage < 1

    asyncio.run(scenario())


def test_conflicting_high_risk_policy_evidence_is_blocked(tmp_path):
    async def conflict_handler(_context, _value):
        return [
            ToolEvidence(
                id="policy:refund:allow",
                content="该商品支持退款。",
                source="refund-policy-a",
                provenance="public_summary",
                metadata={
                    "factType": "policy",
                    "claimKey": "refundEligibility",
                    "claimValue": "allowed",
                    "publisher": "规则中心",
                    "review_status": "current",
                },
            ),
            ToolEvidence(
                id="policy:refund:deny",
                content="该商品不支持退款。",
                source="refund-policy-b",
                provenance="public_summary",
                metadata={
                    "factType": "policy",
                    "claimKey": "refundEligibility",
                    "claimValue": "denied",
                    "publisher": "规则中心",
                    "review_status": "current",
                },
            ),
        ]

    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'conflict-review.db'}")
        Base.metadata.create_all(database.engine)
        registry = ToolRegistry(
            [AgentTool("test.refund", "refund", _Query, conflict_handler)]
        )
        coordinator = AgenticRagCoordinator(
            _FixedPlanner("test.refund"), None, max_steps=1, registry=registry
        )
        with database.session_factory() as db:
            result = await coordinator.run(
                db,
                user_id=1,
                question="鲜活商品没有质量问题，可以按七日无理由退款吗？",
            )

        assert result.terminal_state == "escalated"
        assert result.review_details.decision == "escalate"
        assert result.review_details.risk == "high"
        assert result.review_details.conflicts == (
            "refundEligibility: allowed <> denied",
        )

    asyncio.run(scenario())
