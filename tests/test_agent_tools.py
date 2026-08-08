from __future__ import annotations

import asyncio

import app.application_core  # noqa: F401
from pydantic import BaseModel, Field

from app.framework.database import Base, Database
from app.modules.commerce.models import AssociationRule, Product
from app.modules.rag.agent_tools import AgentTool, ToolContext, ToolEvidence, ToolRegistry, build_tool_registry
from app.modules.support.models import KnowledgeGap, SupportCase
from app.modules.users.models import User


class _Value(BaseModel):
    value: int = Field(gt=0)


def test_tool_contract_validation_error_and_trace_do_not_execute(tmp_path):
    calls = 0

    async def handler(_context, value):
        nonlocal calls
        calls += 1
        return [ToolEvidence(id="ok", content=str(value.value), source="test")]

    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'tools.db'}")
        Base.metadata.create_all(database.engine)
        registry = ToolRegistry([AgentTool("test.validated", "test", _Value, handler)])
        with database.session_factory() as db:
            context = ToolContext(db, 1)
            invalid = await registry.execute("test.validated", {"value": 0}, context)
            assert invalid.status == "error" and invalid.error_code == "TOOL_INPUT_INVALID"
            assert invalid.arguments == {} and calls == 0 and invalid.duration_ms >= 0
            valid = await registry.execute("test.validated", {"value": 2}, context)
            assert valid.status == "success" and valid.arguments == {"value": 2}
            assert valid.evidence[0].content == "2" and calls == 1
    asyncio.run(scenario())


def test_granular_tools_enforce_owner_scope_and_legacy_aliases(tmp_path):
    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'business-tools.db'}")
        Base.metadata.create_all(database.engine)
        with database.session_factory() as db:
            owner = User(username="owner", password_hash="x", role="admin")
            foreign = User(username="foreign", password_hash="x", role="admin")
            db.add_all([owner, foreign]); db.flush()
            first = Product(owner_id=owner.id, source_key="a", name="牛奶", category="乳品")
            second = Product(owner_id=owner.id, source_key="b", name="面包", category="烘焙")
            hidden = Product(owner_id=foreign.id, source_key="c", name="隐私商品", category="其他")
            db.add_all([first, second, hidden]); db.flush()
            db.add(AssociationRule(owner_id=owner.id, import_id=1, antecedent_product_id=first.id, consequent_product_id=second.id, cooccurrence_count=90, support=.2, confidence=.5, lift=1.8, fingerprint="a" * 64))
            db.add_all([
                SupportCase(owner_id=owner.id, case_key="own", customer_name="甲", subject="牛奶退款", is_demo=True),
                SupportCase(owner_id=foreign.id, case_key="foreign", customer_name="乙", subject="隐私投诉"),
                KnowledgeGap(owner_id=owner.id, fingerprint="b" * 64, title="退款时效缺口", category="refund", severity="high"),
            ])
            db.commit()
            registry = build_tool_registry(None)
            context = ToolContext(db, owner.id)
            association = await registry.execute("commerce.search_association_rules", {"query": "牛奶"}, context)
            assert association.status == "success" and association.evidence
            assert "牛奶" in association.evidence[0].content and association.evidence[0].provenance == "derived"
            cases = await registry.execute("support_cases", {"query": "隐私", "limit": 8}, context)
            assert cases.status == "success" and cases.evidence == []
            gaps = await registry.execute("support.get_knowledge_gaps", {"query": "退款"}, context)
            assert gaps.evidence and gaps.evidence[0].metadata["gap_id"]
            metrics = await registry.execute("commerce_data", {"query": "牛奶", "limit": 5}, context)
            assert metrics.status == "success" and registry.canonical_name("commerce_data") == "commerce.get_product_metrics"
    asyncio.run(scenario())
