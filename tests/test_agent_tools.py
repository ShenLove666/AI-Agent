from __future__ import annotations

import asyncio
from datetime import datetime

import app.application_core  # noqa: F401
from pydantic import BaseModel, Field

from app.framework.database import Base, Database
from app.modules.commerce.models import AssociationRule, Product
from app.modules.orders.models import CustomerSnapshot, Fulfillment, Order, Refund
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


def test_order_tools_return_typed_owner_scoped_facts(tmp_path):
    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'order-tools.db'}")
        Base.metadata.create_all(database.engine)
        with database.session_factory() as db:
            owner = User(username="order-tool-owner", password_hash="x")
            foreign = User(username="order-tool-foreign", password_hash="x")
            db.add_all([owner, foreign])
            db.flush()
            customer = CustomerSnapshot(
                owner_id=owner.id,
                customer_key="customer-tool-1",
                display_name="陈女士",
                order_count=6,
                refund_count=1,
                captured_at=datetime(2026, 8, 8, 8, 0),
                is_demo=True,
            )
            db.add(customer)
            db.flush()
            order = Order(
                owner_id=owner.id,
                order_no="NB-TOOL-001",
                customer_snapshot_id=customer.id,
                status="delivering",
                total_amount_minor=8860,
                is_demo=True,
            )
            hidden = Order(
                owner_id=foreign.id,
                order_no="NB-TOOL-HIDDEN",
                status="paid",
                total_amount_minor=100,
            )
            db.add_all([order, hidden])
            db.flush()
            db.add_all(
                [
                    Fulfillment(
                        order_id=order.id,
                        status="delayed",
                        estimated_delivery_at=datetime(2026, 8, 8, 9, 0),
                        delivered_at=datetime(2026, 8, 8, 9, 12),
                        updated_at=datetime(2026, 8, 8, 9, 12),
                    ),
                    Refund(order_id=order.id, status="not_requested", amount_minor=0),
                ]
            )
            db.commit()
            registry = build_tool_registry(None)
            context = ToolContext(db, owner.id)

            order_result = await registry.execute(
                "commerce.get_order", {"order_no": "NB-TOOL-001"}, context
            )
            delivery = await registry.execute(
                "commerce.get_delivery_status",
                {"order_no": "NB-TOOL-001"},
                context,
            )
            refund = await registry.execute(
                "commerce.get_refund_status", {"order_no": "NB-TOOL-001"}, context
            )
            customer_result = await registry.execute(
                "commerce.get_customer_history",
                {"order_no": "NB-TOOL-001"},
                context,
            )
            hidden_result = await registry.execute(
                "commerce.get_order", {"order_no": "NB-TOOL-HIDDEN"}, context
            )
            injected_owner = await registry.execute(
                "commerce.get_order",
                {"order_no": "NB-TOOL-001", "owner_id": foreign.id},
                context,
            )

            assert order_result.status == "success"
            assert order_result.evidence[0].metadata["factType"] == "order"
            assert order_result.evidence[0].provenance == "synthetic"
            assert delivery.evidence[0].metadata["delayMinutes"] == 12
            assert delivery.evidence[0].metadata["delayProvenance"] == "derived"
            assert refund.evidence[0].metadata["status"] == "not_requested"
            assert customer_result.evidence[0].metadata["orderCount"] == 6
            assert hidden_result.status == "success" and hidden_result.evidence == []
            assert injected_owner.error_code == "TOOL_INPUT_INVALID"

    asyncio.run(scenario())
