"""客服处理 Copilot 门禁测试。

覆盖：
1. 已发布 Knowledge Release 真正限制检索（allowed_document_ids 白名单）。
2. 无已发布 release → 禁止知识检索（空元组）。
3. generate_suggestion 把 actor_user_id / data_owner_id 正确传入 Agent。
4. 知识版本管理的 uploader 遗留：商家归属按 KnowledgeBase.owner_id。
5. 事实驱动的对客草稿（不编造、不编时间、兜底模板）。
6. decide 后端风险门禁（high/medium/low + confirmed_facts + 主管放行）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
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


def _agentic_run(
    *,
    results: list[SearchResult],
    risk: str = "low",
    intent: str = "general",
    decision: str = "ready",
    terminal: str = "grounded",
) -> AgenticRun:
    """构造一个模拟 Agent Runtime 返回的 AgenticRun（默认 grounded）。"""
    details = EvidenceReview(
        intent=intent,
        relevance=1,
        coverage=1,
        conflicts=(),
        authority_sufficient=True,
        missing_fields=(),
        risk=risk,
        decision=decision,
        summary="证据相关、覆盖完整且满足风险要求",
    )
    return AgenticRun(
        AgentDecision("research", (), "查询事实", "deterministic_fallback"),
        tuple(results),
        f"{decision}: 测试",
        details,
        (),
        terminal,
        "deterministic_fallback",
    )


class _FakeRouter:
    async def complete(self, request):
        raise AssertionError("RecordingCoordinator 不应调用模型")


class RecordingCoordinator(AgenticRagCoordinator):
    """记录 run() 关键参数的假协调器，返回可配置的 AgenticRun。"""

    def __init__(self, run: AgenticRun | None = None):
        super().__init__(_FakeRouter(), None)
        self.run_result = run or _agentic_run(results=[])
        self.last_actor_user_id: int | None = None
        self.last_data_owner_id: int | None = None
        self.last_allowed_document_ids: tuple[int, ...] | None = None
        self.last_knowledge_base_ids: tuple[int, ...] = ()

    async def run(
        self,
        db,
        *,
        actor_user_id: int | None = None,
        data_owner_id: int | None = None,
        user_id: int | None = None,
        question: str,
        original_question: str | None = None,
        knowledge_base_ids: tuple[int, ...] = (),
        allowed_document_ids: tuple[int, ...] | None = None,
        progress_sink=None,
    ) -> AgenticRun:
        self.last_actor_user_id = (
            actor_user_id if actor_user_id is not None else user_id
        )
        self.last_data_owner_id = (
            data_owner_id if data_owner_id is not None else user_id
        )
        self.last_allowed_document_ids = (
            tuple(allowed_document_ids)
            if allowed_document_ids is not None
            else None
        )
        self.last_knowledge_base_ids = tuple(knowledge_base_ids)
        self.last_question = question
        return self.run_result


def _fixture(tmp_path, *, with_release: bool = True):
    """商家 + 知识库 + 文档 A/B（已发布）/D（未发布）+ release + 工单。"""
    database = Database(f"sqlite:///{tmp_path / 'copilot.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    db = database.session_factory()
    merchant = User(username="merchant", password_hash="hash")
    db.add(merchant)
    db.flush()
    base = KnowledgeBase(owner_id=merchant.id, name="售后规则")
    db.add(base)
    db.flush()

    def make_document(filename: str, *, status: str = "indexed") -> KnowledgeDocument:
        document = KnowledgeDocument(
            knowledge_base_id=base.id,
            uploader_id=merchant.id,
            filename=filename,
            file_type="md",
            storage_path=filename,
            file_size=10,
            status=status,
        )
        db.add(document)
        db.flush()
        return document

    doc_a = make_document("refund-a.md")
    doc_b = make_document("delivery-b.md")
    doc_d = make_document("draft-d.md", status="pending")
    release = None
    if with_release:
        release = KnowledgeRelease(
            owner_id=merchant.id,
            version="v1",
            title="售后基线",
            status="published",
            processing_status="ready",
            content_hash=hashlib.sha256(b"v1").hexdigest(),
            is_active=True,
        )
        db.add(release)
        db.flush()
        for document in (doc_a, doc_b):
            db.add(
                KnowledgeReleaseDocument(
                    release_id=release.id,
                    document_id=document.id,
                    document_hash="x" * 64,
                    filename_snapshot=document.filename,
                )
            )
    case = SupportCase(
        owner_id=merchant.id,
        case_key="case-1",
        customer_name="顾客",
        subject="草莓破损",
        priority="normal",
    )
    db.add(case)
    db.flush()
    db.add(
        SupportMessage(
            case_id=case.id, role="customer", content="草莓坏了，什么时候重新发货？"
        )
    )
    db.add(
        SupportMessage(case_id=case.id, role="agent", content="好的，我为您核实一下。")
    )
    db.commit()
    return database, db, merchant, base, doc_a, doc_b, doc_d, release, case


def test_suggestion_respects_published_release(tmp_path):
    """已发布 release（A、B）+ 未发布 D：白名单 == {A, B}，D 不在其中。"""
    fixture = _fixture(tmp_path, with_release=True)
    database, db, merchant, _base, doc_a, doc_b, doc_d, _release, case = fixture
    coordinator = RecordingCoordinator()
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(
                db, merchant.id, case.id, merchant.id, None, coordinator=coordinator
            )
        )
        assert result["status"] == "completed"
        allowed = coordinator.last_allowed_document_ids
        assert allowed is not None
        assert set(allowed) == {doc_a.id, doc_b.id}
        assert doc_d.id not in allowed
        snapshot = json.loads(db.get(ReplySuggestion, result["id"]).config_snapshot_json)
        assert snapshot["allowedDocumentCount"] == 2
    finally:
        db.close()
        database.engine.dispose()


def test_suggestion_no_release_blocks_knowledge(tmp_path):
    """无 active release：allowed_document_ids == ()，禁止知识检索。"""
    fixture = _fixture(tmp_path, with_release=False)
    database, db, merchant, _base, _a, _b, _d, _release, case = fixture
    coordinator = RecordingCoordinator()
    try:
        result = asyncio.run(
            SupportService().generate_suggestion(
                db, merchant.id, case.id, merchant.id, None, coordinator=coordinator
            )
        )
        assert result["status"] == "completed"
        assert coordinator.last_allowed_document_ids == ()
        snapshot = json.loads(db.get(ReplySuggestion, result["id"]).config_snapshot_json)
        assert snapshot["allowedDocumentCount"] == 0
        assert snapshot["knowledgeVersion"] is None
    finally:
        db.close()
        database.engine.dispose()


def test_agentic_run_actor_data_owner(tmp_path):
    """actor_id/data_owner_id 正确传入 Agent Runtime。"""
    fixture = _fixture(tmp_path, with_release=True)
    database, db, merchant, _base, _a, _b, _d, _release, case = fixture
    actor = User(username="agent-user", password_hash="hash")
    db.add(actor)
    db.commit()
    coordinator = RecordingCoordinator()
    try:
        asyncio.run(
            SupportService().generate_suggestion(
                db, merchant.id, case.id, actor.id, None, coordinator=coordinator
            )
        )
        assert coordinator.last_actor_user_id == actor.id
        assert coordinator.last_data_owner_id == merchant.id
        # 工单上下文为结构化文本（不再只是最后一条消息）
        assert coordinator.last_question.startswith("顾客最新诉求：")
        assert "工单主题：草莓破损" in coordinator.last_question
        assert "最近对话：" in coordinator.last_question
        assert "客服: 好的，我为您核实一下。" in coordinator.last_question
    finally:
        db.close()
        database.engine.dispose()


def test_uploader_owner_legacy_fixed(tmp_path):
    """运营商上传的文档按 KnowledgeBase.owner_id 归属商家。"""
    database = Database(f"sqlite:///{tmp_path / 'owner.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    db = database.session_factory()
    merchant = User(username="merchant", password_hash="hash")
    operator = User(username="operator", password_hash="hash")
    db.add_all([merchant, operator])
    db.flush()
    base = KnowledgeBase(owner_id=merchant.id, name="售后规则")
    db.add(base)
    db.flush()
    document = KnowledgeDocument(
        knowledge_base_id=base.id,
        uploader_id=operator.id,  # 遗留场景：uploader 是运营商，不是商家
        filename="refund.md",
        file_type="md",
        storage_path="refund.md",
        file_size=10,
        status="indexed",
    )
    db.add(document)
    db.commit()
    service = SupportService()
    try:
        # 商家视图能看到运营商上传的文档
        sources = service.knowledge_sources(db, merchant.id)
        assert any(item["id"] == document.id for item in sources)
        # 商家发布版本能纳入运营商上传的文档（旧代码 uploader_id 校验会 404）
        release = service.create_release(
            db,
            merchant.id,
            merchant.id,
            version="v1",
            title="售后基线",
            document_ids=[document.id],
        )
        assert release["version"] == "v1"
        assert any(item["id"] == document.id for item in release["documents"])
    finally:
        db.close()
        database.engine.dispose()


def test_compose_draft_fact_driven(tmp_path):
    """草稿只使用已核实事实：有配送状态无时点 → 明确不能承诺时点；无事实 → 兜底模板。"""
    # 情况 1：配送/退款事实存在但无送达时点 → 状态进入草稿，且不编造具体时间
    run_no_time = _agentic_run(
        results=[
            SearchResult(
                id="order:1",
                content="订单 X 状态为 delivering，金额 5000 CNY（最小货币单位）。",
                score=0.9,
                channel="commerce.get_order",
                metadata={"factType": "order", "orderNo": "X", "status": "delivering"},
            ),
            SearchResult(
                id="delivery:1",
                content="订单 X 配送状态为 out_for_delivery；预计送达 未知。",
                score=0.9,
                channel="commerce.get_delivery_status",
                metadata={"factType": "delivery", "orderNo": "X", "status": "out_for_delivery"},
            ),
            SearchResult(
                id="refund:1",
                content="订单 X 退款状态为 processing。",
                score=0.9,
                channel="commerce.get_refund_status",
                metadata={"factType": "refund", "orderNo": "X", "status": "processing"},
            ),
        ]
    )
    draft = SupportService._compose_draft(run_no_time, "什么时候送到？", "X")
    assert "订单状态为delivering" in draft
    assert "配送状态为out_for_delivery" in draft
    assert "退款状态为processing" in draft
    assert "当前系统暂未提供准确到达时间，我不能为您承诺具体时点" in draft
    assert "预计" not in draft
    assert "已于" not in draft

    # 情况 2：事实带预计送达时点 → 只引用已核实时点
    run_with_time = _agentic_run(
        results=[
            SearchResult(
                id="delivery:2",
                content="订单 X 配送状态为 delivering；预计送达 2026-08-12T10:00:00。",
                score=0.9,
                channel="commerce.get_delivery_status",
                metadata={
                    "factType": "delivery",
                    "orderNo": "X",
                    "status": "delivering",
                    "estimatedDeliveryAt": "2026-08-12T10:00:00",
                },
            ),
        ]
    )
    draft = SupportService._compose_draft(run_with_time, "什么时候送到？", "X")
    assert "预计2026-08-12T10:00:00送达" in draft

    # 情况 3：无任何事实 → 兜底模板
    run_empty = _agentic_run(results=[])
    draft = SupportService._compose_draft(run_empty, "你好", None)
    assert "已收到并完成初步核实" in draft


def test_decide_risk_gate(tmp_path):
    """decide 风险门禁：high → 403（普通坐席）/ 主管放行；medium → 需确认；low → 直发。"""
    database = Database(f"sqlite:///{tmp_path / 'gate.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    db = database.session_factory()
    owner = User(username="merchant", password_hash="hash")
    agent = User(username="agent", password_hash="hash")
    supervisor = User(username="supervisor", password_hash="hash", role="supervisor")
    db.add_all([owner, agent, supervisor])
    db.flush()
    case = SupportCase(
        owner_id=owner.id,
        case_key="case-1",
        customer_name="顾客",
        subject="退款问题",
        priority="normal",
    )
    db.add(case)
    db.flush()
    db.commit()

    def make_suggestion(risk: str) -> ReplySuggestion:
        suggestion = ReplySuggestion(
            case_id=case.id,
            requested_by=agent.id,
            status="completed",
            content="您好，已为您核实相关情况。",
            citations_json="[]",
            risk_flags_json="[]",
            model_id="test",
            prompt_version="support-v2-agentic",
            config_snapshot_json=json.dumps(
                {"resolution": {"risk": risk}}, ensure_ascii=False
            ),
        )
        db.add(suggestion)
        db.flush()
        return suggestion

    service = SupportService()
    try:
        # high + 普通坐席 accepted → 403
        high = make_suggestion("high")
        with pytest.raises(AppError) as exc:
            service.decide(
                db, owner.id, case.id, high.id, agent.id, "accepted", None, None
            )
        assert exc.value.status_code == 403
        assert exc.value.code == "HIGH_RISK_REQUIRES_ESCALATION"

        # high + 主管 → 放行
        high_supervisor = make_suggestion("high")
        result = service.decide(
            db,
            owner.id,
            case.id,
            high_supervisor.id,
            supervisor.id,
            "accepted",
            None,
            None,
        )
        assert result["messages"][-1]["content"] == high_supervisor.content
        assert (
            db.query(ReplyDecision)
            .filter_by(suggestion_id=high_supervisor.id, decision="accepted")
            .count()
            == 1
        )

        # medium 无确认 → 422
        medium = make_suggestion("medium")
        with pytest.raises(AppError) as exc:
            service.decide(
                db, owner.id, case.id, medium.id, agent.id, "accepted", None, None
            )
        assert exc.value.status_code == 422
        assert exc.value.code == "RISK_CONFIRMATION_REQUIRED"

        # medium + confirmed_facts=True → 放行
        medium_confirmed = make_suggestion("medium")
        result = service.decide(
            db,
            owner.id,
            case.id,
            medium_confirmed.id,
            agent.id,
            "accepted",
            None,
            None,
            confirmed_facts=True,
        )
        assert result["messages"][-1]["content"] == medium_confirmed.content

        # low → 现有流程直接放行
        low = make_suggestion("low")
        result = service.decide(
            db, owner.id, case.id, low.id, agent.id, "accepted", None, None
        )
        assert result["messages"][-1]["content"] == low.content

        # escalated 决策路径不受门禁影响（high 风险仍可升级）
        escalated = make_suggestion("high")
        result = service.decide(
            db,
            owner.id,
            case.id,
            escalated.id,
            agent.id,
            "escalated",
            None,
            "需主管复核",
        )
        assert result["status"] == "escalated"
    finally:
        db.close()
        database.engine.dispose()
