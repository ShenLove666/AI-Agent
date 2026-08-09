from __future__ import annotations

import tempfile

import pytest
from sqlalchemy import event

from app.framework.database import Database
from app.framework.errors import AppError
from app.framework.migrations import upgrade_database
from app.modules.support.models import SupportCase
from app.modules.support.service import SupportService
from app.modules.users.models import User


def _fixture():
    database = Database(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    event.listen(
        database.engine,
        "connect",
        lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"),
    )
    upgrade_database(database)
    db = database.session_factory()
    user = User(username="merchant", password_hash="hash")
    db.add(user)
    db.flush()
    case = SupportCase(
        owner_id=user.id,
        case_key="esc-1",
        customer_name="顾客",
        subject="牛奶变质要求赔偿",
        priority="high",
    )
    db.add(case)
    db.flush()
    db.commit()
    return database, db, user, case


def test_raise_escalation_marks_case_and_blocks_duplicate():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        result = service.raise_escalation(
            db,
            user.id,
            case.id,
            user.id,
            "food_safety",
            "顾客要求三倍赔偿，缺少赔偿依据",
            "high",
            {"intent": "food_safety", "risk": "high"},
        )
        assert result["status"] == "pending"
        assert result["category"] == "food_safety"
        assert result["riskLevel"] == "high"
        assert result["case"]["subject"] == "牛奶变质要求赔偿"
        persisted = db.get(SupportCase, case.id)
        assert persisted is not None
        assert persisted.status == "escalated"

        with pytest.raises(AppError) as exc:
            service.raise_escalation(
                db, user.id, case.id, user.id, "food_safety", "再升一次"
            )
        assert exc.value.status_code == 409
    finally:
        db.close()
        database.engine.dispose()


def test_escalation_requires_reason_and_valid_category():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        with pytest.raises(AppError) as exc:
            service.raise_escalation(db, user.id, case.id, user.id, "food_safety", "  ")
        assert exc.value.status_code == 422
        with pytest.raises(AppError) as exc:
            service.raise_escalation(
                db, user.id, case.id, user.id, "unknown_cat", "原因"
            )
        assert exc.value.status_code == 422
    finally:
        db.close()
        database.engine.dispose()


def test_supervisor_resolves_the_shared_demo_support_owner():
    database, db, demo_owner, _case = _fixture()
    try:
        demo_owner.is_demo = True
        supervisor = User(
            username="support-supervisor",
            password_hash="hash",
            role="supervisor",
        )
        db.add(supervisor)
        db.commit()

        assert SupportService().owner_for(db, supervisor) == demo_owner.id
    finally:
        db.close()
        database.engine.dispose()


def test_supervisor_queue_accept_and_resolve():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        raised = service.raise_escalation(
            db, user.id, case.id, user.id, "compensation_request", "顾客要求额外补偿"
        )
        queue = service.escalation_queue(db, user.id)
        assert len(queue) == 1
        assert queue[0]["id"] == raised["id"]

        accepted = service.accept_escalation(db, user.id, raised["id"], user.id)
        assert accepted["status"] == "accepted"
        assert accepted["assignedTo"] == user.id

        resolved = service.resolve_escalation(
            db, user.id, raised["id"], user.id, "approved_refund", "全额退款并收集照片"
        )
        assert resolved["status"] == "resolved"
        assert resolved["resolution"] == "approved_refund"
        persisted = db.get(SupportCase, case.id)
        assert persisted is not None
        assert persisted.status == "resolved"
    finally:
        db.close()
        database.engine.dispose()


def test_supervisor_return_returns_case_to_agent():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        raised = service.raise_escalation(
            db, user.id, case.id, user.id, "policy_uncertain", "规则不清"
        )
        returned = service.return_escalation(
            db, user.id, raised["id"], user.id, "按退款规则回复即可"
        )
        assert returned["status"] == "returned"
        assert returned["resolution"] == "return_to_agent"
        persisted = db.get(SupportCase, case.id)
        assert persisted is not None
        assert persisted.status == "in_progress"
    finally:
        db.close()
        database.engine.dispose()


def test_request_more_evidence_keeps_case_escalated():
    """要求补充材料/转专员不是最终解决：工单保持 escalated，等待后续处理。"""
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        raised = service.raise_escalation(
            db, user.id, case.id, user.id, "food_safety", "食品安全需补充材料"
        )
        pending_evidence = service.resolve_escalation(
            db,
            user.id,
            raised["id"],
            user.id,
            "request_more_evidence",
            "请补充商品照片与批次",
        )
        assert pending_evidence["status"] == "accepted"
        assert pending_evidence["resolution"] == "request_more_evidence"
        assert pending_evidence["assignedTo"] == user.id
        assert pending_evidence["resolvedAt"] is None
        persisted = db.get(SupportCase, case.id)
        assert persisted is not None
        assert persisted.status == "escalated"
    finally:
        db.close()
        database.engine.dispose()


def test_transfer_specialist_uses_transferred_lifecycle_state():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        raised = service.raise_escalation(
            db, user.id, case.id, user.id, "food_safety", "需要食品安全专员处理"
        )
        transferred = service.resolve_escalation(
            db,
            user.id,
            raised["id"],
            user.id,
            "transfer_specialist",
            "已转食品安全专员",
        )

        assert transferred["status"] == "transferred"
        assert transferred["resolution"] == "transfer_specialist"
        assert transferred["resolvedAt"] is not None
        persisted = db.get(SupportCase, case.id)
        assert persisted is not None
        assert persisted.status == "escalated"
    finally:
        db.close()
        database.engine.dispose()


def test_escalation_overview_counts():
    database, db, user, case = _fixture()
    service = SupportService()
    try:
        raised = service.raise_escalation(
            db, user.id, case.id, user.id, "food_safety", "食品安全", "high"
        )
        service.accept_escalation(db, user.id, raised["id"], user.id)
        service.resolve_escalation(
            db, user.id, raised["id"], user.id, "approved_refund"
        )

        overview = service.escalation_overview(db, user.id)
        assert overview["total"] == 1
        assert overview["resolved"] == 1
        assert overview["highRisk"] == 0
        assert overview["byCategory"]["food_safety"] == 1
    finally:
        db.close()
        database.engine.dispose()
