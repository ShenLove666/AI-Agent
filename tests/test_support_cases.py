from __future__ import annotations

import json

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.support.models import SupportCase, SupportEvent, SupportMessage
from app.modules.support.service import SupportService
from app.modules.users.models import User


def _database(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'support.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    return database


def _seed(db):
    owner = User(username="merchant", password_hash="hash", role="admin")
    outsider = User(username="outsider", password_hash="hash")
    db.add_all([owner, outsider]); db.flush()
    first = SupportCase(
        owner_id=owner.id,
        case_key="case-001",
        customer_name="林女士",
        subject="草莓破损退款",
        status="pending",
        priority="urgent",
        labels_json=json.dumps(["refund", "fresh"]),
    )
    hidden = SupportCase(
        owner_id=outsider.id,
        case_key="other-001",
        customer_name="其他顾客",
        subject="不可见",
        status="pending",
        priority="urgent",
    )
    db.add_all([first, hidden]); db.flush()
    db.add(SupportMessage(case_id=first.id, role="customer", content="草莓坏了，优惠券退吗？"))
    db.commit()
    return owner, outsider, first


def test_inbox_filters_and_ownership(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, outsider, case = _seed(db)
        service = SupportService()
        rows = service.list_cases(db, owner.id, status="pending", priority="urgent", label="refund", search="草莓")
        assert [item["id"] for item in rows] == [case.id]
        with pytest.raises(AppError) as exc:
            service.detail(db, outsider.id, case.id)
        assert exc.value.status_code == 404


def test_transition_requires_resolution_and_detects_conflict(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, _, case = _seed(db)
        service = SupportService()
        with pytest.raises(AppError) as exc:
            service.transition(db, owner.id, case.id, owner.id, status="resolved", expected_version=1)
        assert exc.value.code == "RESOLUTION_CODE_REQUIRED"
        result = service.transition(db, owner.id, case.id, owner.id, status="in_progress", expected_version=1)
        assert result["status"] == "in_progress"
        assert db.scalar(db.query(SupportEvent).filter_by(case_id=case.id).statement) is not None
        with pytest.raises(AppError) as conflict:
            service.transition(db, owner.id, case.id, owner.id, status="escalated", expected_version=1)
        assert conflict.value.status_code == 409


def test_manual_reply_remains_available_without_ai(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, _, case = _seed(db)
        result = SupportService().manual_reply(db, owner.id, case.id, owner.id, "已为您登记售后，请保留商品照片。")
        assert result["messages"][-1]["role"] == "agent"
        assert result["messages"][-1]["sentToCustomer"] is True

