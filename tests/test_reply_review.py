from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.support.models import KnowledgeRelease, KnowledgeReleaseDocument, ReplyDecision, ReplySuggestion, SupportCase, SupportMessage
from app.modules.support.service import SupportService
from app.modules.users.models import User


class FakeRouter:
    async def complete(self, request):
        assert "已发布资料" in request.messages[-1].content
        return "您好，商品破损可提交照片申请售后；优惠券返还以审核结果为准，请由客服确认。"


def _fixture(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'reply.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    db = database.session_factory()
    user = User(username="merchant", password_hash="hash"); db.add(user); db.flush()
    base = KnowledgeBase(owner_id=user.id, name="售后规则"); db.add(base); db.flush()
    document = KnowledgeDocument(knowledge_base_id=base.id, uploader_id=user.id, filename="refund.md", file_type="md", storage_path="refund.md", file_size=10, status="indexed")
    db.add(document); db.flush()
    chunk = KnowledgeChunk(knowledge_base_id=base.id, document_id=document.id, position=0, content="生鲜破损应保留照片，审核后退款；优惠券按活动规则返还。", enabled=True)
    db.add(chunk)
    release = KnowledgeRelease(owner_id=user.id, version="v1", title="售后基线", status="published", processing_status="ready", content_hash=hashlib.sha256(b"v1").hexdigest(), is_active=True)
    db.add(release); db.flush()
    db.add(KnowledgeReleaseDocument(release_id=release.id, document_id=document.id, document_hash="x" * 64, filename_snapshot=document.filename))
    case = SupportCase(owner_id=user.id, case_key="case-1", customer_name="顾客", subject="草莓破损", priority="urgent")
    db.add(case); db.flush()
    db.add(SupportMessage(case_id=case.id, role="customer", content="草莓坏了，退款后优惠券会退吗？")); db.commit()
    return database, db, user, case


def test_grounded_suggestion_has_snapshot_citations_and_risk(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    try:
        result = asyncio.run(SupportService().generate_suggestion(db, user.id, case.id, user.id, FakeRouter()))
        assert result["status"] == "completed"
        assert result["citations"][0]["releaseVersion"] == "v1"
        assert "refund_review" in result["riskFlags"]
        persisted = db.get(ReplySuggestion, result["id"])
        assert json.loads(persisted.config_snapshot_json) == {"knowledgeVersion": "v1"}
    finally:
        db.close(); database.engine.dispose()


def test_provider_unavailable_is_persisted_without_sending(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    try:
        result = asyncio.run(SupportService().generate_suggestion(db, user.id, case.id, user.id, None))
        assert result["status"] == "provider_unavailable"
        sent = db.query(SupportMessage).filter_by(case_id=case.id, sent_to_customer=True).count()
        assert sent == 0
    finally:
        db.close(); database.engine.dispose()


def test_edit_preserves_suggestion_and_prevents_second_decision(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    try:
        service = SupportService()
        generated = asyncio.run(service.generate_suggestion(db, user.id, case.id, user.id, FakeRouter()))
        original = generated["content"]
        result = service.decide(db, user.id, case.id, generated["id"], user.id, "edited", "人工修订后的最终回复", None)
        assert result["messages"][-1]["content"] == "人工修订后的最终回复"
        assert db.get(ReplySuggestion, generated["id"]).content == original
        assert db.query(ReplyDecision).filter_by(suggestion_id=generated["id"]).count() == 1
        with pytest.raises(AppError) as exc:
            service.decide(db, user.id, case.id, generated["id"], user.id, "accepted", None, None)
        assert exc.value.status_code == 409
    finally:
        db.close(); database.engine.dispose()

