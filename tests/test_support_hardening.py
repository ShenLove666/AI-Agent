"""正确性加固回归：状态机矩阵、回复长度上限、质检归属校验、金额换算。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.rag.agent_tools import _format_money


@contextmanager
def _expect_code(code: str):
    try:
        yield
    except AppError as exc:
        assert exc.code == code, f"期望 {code}，实际 {exc.code}"
    else:
        raise AssertionError(f"期望抛出 {code}，实际未抛出")


def test_format_money_converts_cny_minor_to_major():
    assert _format_money(7470, "CNY") == "74.70 CNY"
    assert _format_money(50, "CNY") == "0.50 CNY"
    assert _format_money(120000, "CNY") == "1200.00 CNY"
    # 非 CNY 货币保守展示原始 minor 并明确标注，避免错误换算
    assert _format_money(5000, "USD") == "5000 USD（最小货币单位）"


def test_transition_matrix_blocks_illegal_jumps(tmp_path: Path):
    from app.modules.support.models import SupportCase
    from app.modules.support.service import SupportService
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'hardening.db'}")
    Base.metadata.create_all(database.engine)
    service = SupportService()
    with database.session_factory() as db:
        owner = User(username="hardening-owner", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        case = SupportCase(
            owner_id=owner.id,
            case_key="hardening-1",
            customer_name="顾客",
            subject="退款问题",
        )
        db.add(case)
        db.flush()
        db.commit()

        # pending → escalated 直接流转被拒（升级必须走 raise_escalation 建台账）
        with _expect_code("INVALID_CASE_TRANSITION"):
            service.transition(
                db, owner.id, case.id, owner.id,
                status="escalated", expected_version=case.version,
            )
        # 正常解决后进入终态
        service.transition(
            db, owner.id, case.id, owner.id,
            status="resolved", expected_version=case.version,
            resolution_code="refund_processed",
        )
        db.refresh(case)
        # resolved 终态不可再流转
        with _expect_code("INVALID_CASE_TRANSITION"):
            service.transition(
                db, owner.id, case.id, owner.id,
                status="in_progress", expected_version=case.version,
            )


def test_manual_reply_rejects_overlong_content(tmp_path: Path):
    from app.modules.support.models import SupportCase
    from app.modules.support.service import SupportService
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'reply-len.db'}")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username="reply-len-owner", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        case = SupportCase(
            owner_id=owner.id,
            case_key="reply-len-1",
            customer_name="顾客",
            subject="咨询",
        )
        db.add(case)
        db.commit()
        with _expect_code("REPLY_TOO_LONG"):
            SupportService().manual_reply(
                db, owner.id, case.id, owner.id, "x" * 4001
            )


def test_quality_label_rejects_foreign_suggestion(tmp_path: Path):
    from app.modules.support.models import ReplySuggestion, SupportCase
    from app.modules.support.service import SupportService
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'quality-owner.db'}")
    Base.metadata.create_all(database.engine)
    service = SupportService()
    with database.session_factory() as db:
        owner = User(username="quality-owner", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        case_a = SupportCase(
            owner_id=owner.id, case_key="qa-1", customer_name="顾客A", subject="甲"
        )
        case_b = SupportCase(
            owner_id=owner.id, case_key="qa-2", customer_name="顾客B", subject="乙"
        )
        db.add_all([case_a, case_b])
        db.flush()
        suggestion_b = ReplySuggestion(
            case_id=case_b.id,
            requested_by=owner.id,
            status="ready",
            model_id="test-model",
            prompt_version="v1",
        )
        db.add(suggestion_b)
        db.flush()
        db.commit()

        # 用属于 case_b 的建议给 case_a 打质检标签 → 归属校验拒绝
        with _expect_code("SUGGESTION_NOT_FOUND"):
            service.add_quality_label(
                db,
                owner.id,
                case_a.id,
                owner.id,
                verdict="failed",
                failure_category="policy",
                severity="high",
                note=None,
                suggestion_id=suggestion_b.id,
            )


def test_quality_label_accepts_own_suggestion(tmp_path: Path):
    from app.modules.support.models import ReplySuggestion, SupportCase
    from app.modules.support.service import SupportService
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'quality-own.db'}")
    Base.metadata.create_all(database.engine)
    service = SupportService()
    with database.session_factory() as db:
        owner = User(username="quality-own-owner", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        case = SupportCase(
            owner_id=owner.id, case_key="qo-1", customer_name="顾客", subject="丙"
        )
        db.add(case)
        db.flush()
        suggestion = ReplySuggestion(
            case_id=case.id,
            requested_by=owner.id,
            status="ready",
            model_id="test-model",
            prompt_version="v1",
        )
        db.add(suggestion)
        db.flush()
        db.commit()

        result = service.add_quality_label(
            db,
            owner.id,
            case.id,
            owner.id,
            verdict="failed",
            failure_category="policy",
            severity="high",
            note=None,
            suggestion_id=suggestion.id,
        )
        assert result["caseId"] == case.id
        assert result["failureCategory"] == "policy"
