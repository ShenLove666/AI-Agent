from __future__ import annotations

import json

from sqlalchemy import event, select

from app.application import create_app
from app.framework.config import Settings
from app.framework.database import Base
from app.modules.commerce.service import RetailService
from app.modules.demo.service import DemoSeedService
from app.modules.support.models import SupportCase, SupportMessage
from app.modules.users.models import User


def test_expanded_support_scenarios_are_source_linked_and_truthful(tmp_path, monkeypatch):
    monkeypatch.delenv("EMBED_MODEL_PATH", raising=False)
    monkeypatch.setenv("VECTOR_BACKEND", "disabled")
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'scenarios.db'}"))
    event.listen(
        app.state.container.database.engine,
        "connect",
        lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(app.state.container.database.engine)
    try:
        with app.state.container.database.session_factory() as db:
            demo = DemoSeedService(app.state.container)
            demo.seed(db, password="StrongDemo123!")
            owner = db.scalar(select(User).where(User.is_demo.is_(True)))
            RetailService().import_managed_snapshots(db, owner.id)
            demo.expand_grounded_support(db, target_cases=360)

            cases = list(
                db.scalars(
                    select(SupportCase)
                    .where(SupportCase.owner_id == owner.id)
                    .order_by(SupportCase.case_key)
                )
            )
            assert len(cases) == 360
            required = {
                "refund", "cancellation", "promotion", "product", "delivery",
                "payment", "food_safety", "invoice", "account",
            }
            categories = {json.loads(case.labels_json)[0] for case in cases}
            assert required <= categories
            assert all(case.source_data_id and case.source_record_key for case in cases)
            assert all(case.generator_version == "retail-support-v3" for case in cases)

            for case in cases:
                lineage = json.loads(case.field_lineage_json)
                assert lineage["product"]["provenance"] == "observed"
                assert lineage["source_record_key"]["provenance"] == "observed"
                assert lineage["customer_wording"]["provenance"] == "synthetic"
                assert lineage["issue_reason"]["provenance"] == "synthetic"
                assert lineage["resolution"]["provenance"] == "synthetic"

            cancellations = [case for case in cases if json.loads(case.labels_json)[0] == "cancellation"]
            assert cancellations
            for case in cancellations:
                lineage = json.loads(case.field_lineage_json)
                assert lineage["invoice_status"]["provenance"] == "observed"
                assert "unavailable" in lineage["cancellation_reason"]["method"]
                message = db.scalar(
                    select(SupportMessage.content)
                    .where(SupportMessage.case_id == case.id, SupportMessage.role == "customer")
                )
                assert "不包含退款原因或到账状态" in message

            review_cases = [case for case in cases if "policy_review" in json.loads(case.labels_json)]
            assert review_cases
            assert all("鲜活商品退货边界" in case.subject for case in review_cases)
    finally:
        app.state.container.database.engine.dispose()
