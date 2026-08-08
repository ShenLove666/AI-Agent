from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.rag.agentic import (
    AgentDecision,
    AgenticRagCoordinator,
    AgenticRun,
    EvidenceReview,
)
from app.modules.retrieval.models import SearchResult
from app.modules.support.models import (
    KnowledgeRelease,
    KnowledgeReleaseDocument,
    ReplyDecision,
    ReplySuggestion,
    SupportCase,
    SupportMessage,
)
from app.modules.support.service import SupportService
from app.modules.users.models import User


def _agentic_run(*, grounded: bool, order_no: str | None = None) -> AgenticRun:
    """构造一个模拟 Agent Runtime 返回的 AgenticRun。"""
    decision = AgentDecision(
        "research",
        (),
        "查询订单与政策证据",
        "deterministic_fallback",
    )
    results = [
        SearchResult(
            id="policy:1",
            content="生鲜破损应保留照片，审核后退款；优惠券按活动规则返还。",
            score=0.9,
            channel="knowledge.search",
            metadata={
                "factType": "policy",
                "document_id": 1,
                "document_name": "refund.md",
                "release_version": "v1",
                "provenance": "source",
            },
        ),
    ]
    if grounded and order_no:
        results.append(
            SearchResult(
                id=f"order:{order_no}",
                content=f"订单 {order_no} 状态为已签收，退款状态为无。",
                score=0.95,
                channel="commerce.get_order",
                metadata={"factType": "order", "orderNo": order_no},
            )
        )
    details = EvidenceReview(
        intent="refund_policy",
        relevance=1,
        coverage=1,
        conflicts=(),
        authority_sufficient=True,
        missing_fields=(),
        risk="high",
        decision="ready" if grounded else "escalate",
        summary="证据相关、覆盖完整且满足风险要求"
        if grounded
        else "证据不足，需人工复核",
    )
    return AgenticRun(
        decision,
        tuple(results),
        "ready: 证据相关、覆盖完整且满足风险要求" if grounded else "escalate: 证据不足",
        details,
        (),
        "grounded" if grounded else "escalated",
        "deterministic_fallback",
    )


class FakeCoordinator(AgenticRagCoordinator):
    """模拟 AgenticRagCoordinator，验证 SupportService 是否正确消费 AgenticRun。"""

    def __init__(self, *, grounded: bool = True, order_no: str | None = None):
        super().__init__(None, None)
        self.grounded = grounded
        self.order_no = order_no
        self.last_question: str | None = None
        self.last_knowledge_base_ids: tuple[int, ...] = ()

    async def run(
        self,
        db,
        *,
        user_id: int,
        question: str,
        knowledge_base_ids: tuple[int, ...] = (),
    ) -> AgenticRun:
        self.last_question = question
        self.last_knowledge_base_ids = tuple(knowledge_base_ids)
        return _agentic_run(grounded=self.grounded, order_no=self.order_no)


def _fixture(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'reply.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    db = database.session_factory()
    user = User(username="merchant", password_hash="hash")
    db.add(user)
    db.flush()
    base = KnowledgeBase(owner_id=user.id, name="售后规则")
    db.add(base)
    db.flush()
    document = KnowledgeDocument(
        knowledge_base_id=base.id,
        uploader_id=user.id,
        filename="refund.md",
        file_type="md",
        storage_path="refund.md",
        file_size=10,
        status="indexed",
    )
    db.add(document)
    db.flush()
    chunk = KnowledgeChunk(
        knowledge_base_id=base.id,
        document_id=document.id,
        position=0,
        content="生鲜破损应保留照片，审核后退款；优惠券按活动规则返还。",
        enabled=True,
    )
    db.add(chunk)
    release = KnowledgeRelease(
        owner_id=user.id,
        version="v1",
        title="售后基线",
        status="published",
        processing_status="ready",
        content_hash=hashlib.sha256(b"v1").hexdigest(),
        is_active=True,
    )
    db.add(release)
    db.flush()
    db.add(
        KnowledgeReleaseDocument(
            release_id=release.id,
            document_id=document.id,
            document_hash="x" * 64,
            filename_snapshot=document.filename,
        )
    )
    case = SupportCase(
        owner_id=user.id,
        case_key="case-1",
        customer_name="顾客",
        subject="草莓破损",
        priority="urgent",
    )
    db.add(case)
    db.flush()
    db.add(
        SupportMessage(
            case_id=case.id, role="customer", content="草莓坏了，退款后优惠券会退吗？"
        )
    )
    db.commit()
    return database, db, user, case


def test_grounded_suggestion_has_citations_and_structured_resolution(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    coordinator = FakeCoordinator(order_no=None)
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(
                db, user.id, case.id, user.id, None, coordinator=coordinator
            )
        )
        assert result["status"] == "completed"
        assert result["citations"][0]["releaseVersion"] == "v1"
        assert "refund_review" in result["riskFlags"]
        assert coordinator.last_question == "草莓坏了，退款后优惠券会退吗？"
        persisted = db.get(ReplySuggestion, result["id"])
        assert persisted is not None
        snapshot = json.loads(persisted.config_snapshot_json)
        assert snapshot["knowledgeVersion"] == "v1"
        assert snapshot["runtimeMode"] == "deterministic_fallback"
        assert snapshot["terminalState"] == "grounded"
        resolution = snapshot["resolution"]
        assert resolution["intent"] == "refund_policy"
        assert resolution["risk"] == "high"
        assert resolution["canSend"] is True
        assert resolution["escalationReason"] is None
        assert resolution["draftReply"]
        assert "转人工" not in resolution["recommendedActions"]
    finally:
        db.close()
        database.engine.dispose()


def test_order_context_is_passed_to_coordinator_when_case_has_order(tmp_path):
    from app.modules.orders.models import Order

    database, db, user, case = _fixture(tmp_path)
    order = Order(
        owner_id=user.id,
        order_no="NB-20260808-001",
        status="delivering",
        total_amount_minor=5000,
    )
    db.add(order)
    db.flush()
    case.order_id = order.id
    db.commit()
    coordinator = FakeCoordinator(order_no="NB-20260808-001")
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(
                db, user.id, case.id, user.id, None, coordinator=coordinator
            )
        )
        assert result["status"] == "completed"
        assert coordinator.last_question is not None
        assert "NB-20260808-001" in coordinator.last_question
        persisted = db.get(ReplySuggestion, result["id"])
        assert persisted is not None
        resolution = json.loads(persisted.config_snapshot_json)["resolution"]
        assert any(fact["type"] == "order" for fact in resolution["facts"])
    finally:
        db.close()
        database.engine.dispose()


def test_escalated_suggestion_cannot_send(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    coordinator = FakeCoordinator(grounded=False)
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(
                db, user.id, case.id, user.id, None, coordinator=coordinator
            )
        )
        assert result["status"] == "insufficient_evidence"
        assert result["errorCode"] == "ESCALATED"
        persisted = db.get(ReplySuggestion, result["id"])
        assert persisted is not None
        snapshot = json.loads(persisted.config_snapshot_json)
        assert snapshot["resolution"]["canSend"] is False
        assert snapshot["resolution"]["escalationReason"]
    finally:
        db.close()
        database.engine.dispose()


def test_provider_unavailable_is_persisted_without_sending(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(db, user.id, case.id, user.id, None)
        )
        assert result["status"] == "provider_unavailable"
        sent = (
            db.query(SupportMessage)
            .filter_by(case_id=case.id, sent_to_customer=True)
            .count()
        )
        assert sent == 0
    finally:
        db.close()
        database.engine.dispose()


def test_edit_preserves_suggestion_and_prevents_second_decision(tmp_path):
    database, db, user, case = _fixture(tmp_path)
    coordinator = FakeCoordinator()
    try:
        service = SupportService()
        generated = asyncio.run(
            service.generate_suggestion(
                db, user.id, case.id, user.id, None, coordinator=coordinator
            )
        )
        original = generated["content"]
        result = service.decide(
            db,
            user.id,
            case.id,
            generated["id"],
            user.id,
            "edited",
            "人工修订后的最终回复",
            None,
        )
        assert result["messages"][-1]["content"] == "人工修订后的最终回复"
        persisted = db.get(ReplySuggestion, generated["id"])
        assert persisted is not None
        assert persisted.content == original
        assert (
            db.query(ReplyDecision).filter_by(suggestion_id=generated["id"]).count()
            == 1
        )
        with pytest.raises(AppError) as exc:
            service.decide(
                db, user.id, case.id, generated["id"], user.id, "accepted", None, None
            )
        assert exc.value.status_code == 409
    finally:
        db.close()
        database.engine.dispose()
