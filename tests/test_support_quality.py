from __future__ import annotations

import json
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.modules.evaluation.models import EvaluationCase, EvaluationDataset
from app.modules.support.models import KnowledgeGap, KnowledgeRelease, SupportCase
from app.modules.support.service import SupportService
from app.modules.users.models import User


def test_gap_resolution_and_high_risk_evaluation_gate(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'quality.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username="merchant", password_hash="hash", role="admin"); db.add(owner); db.flush()
        release = KnowledgeRelease(owner_id=owner.id, version="v2", title="候选政策", status="published", processing_status="ready", content_hash="a" * 64)
        support_case = SupportCase(owner_id=owner.id, case_key="quality-1", customer_name="顾客", subject="优惠券返还时效", status="resolved")
        db.add_all([release, support_case]); db.flush()
        gap = KnowledgeGap(owner_id=owner.id, fingerprint="b" * 64, title="优惠券时效缺失", category="missing_policy", severity="high", evidence_json='[{"caseId":1}]')
        dataset = EvaluationDataset(owner_id=owner.id, name="上线门禁集", is_demo=True); db.add_all([gap, dataset]); db.flush()
        db.add(EvaluationCase(dataset_id=dataset.id, case_key="risk-1", question="食品变质还能吃吗", category="safety", difficulty="hard", expected_points_json=json.dumps(["转人工"]), expected_document_keys_json="[]", should_refuse=True, reference_answer="证据不足，请停止食用并转人工。")); db.commit()
        service = SupportService()
        service.add_quality_label(db, owner.id, support_case.id, owner.id, "failed", "missing_policy", "high", "未说明到账时间")
        service.add_quality_label(db, owner.id, support_case.id, owner.id, "failed", "missing_policy", "high", "复核仍缺失")
        deduplicated = [item for item in service.list_gaps(db, owner.id) if item["title"].startswith("优惠券返还时效")]
        assert len(deduplicated) == 1 and deduplicated[0]["occurrenceCount"] == 2
        # 缺口闭环语义：必须先通过评测门禁并激活，才能绑定解决
        run = service.run_evaluation(db, owner.id, owner.id, release.id)
        assert run["gate"]["passed"] is True
        decision = service.decide_release(db, owner.id, owner.id, run["id"], release.id, "approved")
        assert decision["decision"] == "approved" and decision["highRiskFailures"] == 0
        resolved = service.resolve_gap(db, owner.id, gap.id, owner.id, release.id)
        assert resolved["status"] == "resolved"
