"""「知识库明明存在却 0 evidence」链路回归测试。

覆盖：
1. owner 域：operator 绑定组织后以商家 owner 视角看到商家数据
   （knowledge.search 命中商家 KB chunk、commerce 工具命中商家关联规则）。
2. 跨商家 knowledgeBaseId 被 prepare 403 拒绝（KNOWLEDGE_BASE_FORBIDDEN）。
3. 向量索引失败不降级文档可用性：status=indexed + vector_indexed=False，
   关键词检索仍可命中；向量成功 → vector_indexed=True；parse 失败 → failed。
4. source_kind → factType 映射：knowledge 证据不再被默认归为 policy。
5. Planner 工具选择：搭配/推荐类问题同时选择 commerce + knowledge。
6. Evidence Reviewer：仅知识库推荐证据时放行但标注「知识库建议」；
   带「销售数据」强要求词时不允许用知识库建议替代。
7. knowledge.search 全部通道失败 → status=failed（RETRIEVAL_FAILED），
   不显示为 0 evidence；用户侧文案「知识检索暂时失败」。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

import app.application_core  # noqa: F401  (注册全部 ORM 模型)
from app.framework.database import Database
from app.framework.errors import AppError, RetrievalError
from app.framework.migrations import upgrade_database
from app.modules.commerce.models import AssociationRule, Product
from app.modules.conversations.service import ConversationService
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.knowledge.search import SqlKeywordSearchChannel
from app.modules.knowledge.service import KnowledgeService
from app.modules.rag.agent_tools import ToolContext, build_tool_registry
from app.modules.rag.agentic import AgenticRagCoordinator
from app.modules.rag.schemas import ChatRequest
from app.modules.rag.service import RagChatService
from app.modules.retrieval.models import RetrievalRequest, SearchResult
from app.modules.users.access import resolve_owner
from app.modules.users.models import Organization, OrganizationMember, User


def _database(tmp_path: Path, name: str = "zero-evidence.db") -> Database:
    database = Database(f"sqlite:///{tmp_path / name}")
    upgrade_database(database)
    return database


def _seed_merchant(db, owner_id: int, prefix: str = "牛肉") -> dict:
    """给商家构造 知识库 chunk + 商品/关联规则，返回可断言的句柄。"""
    base = KnowledgeBase(owner_id=owner_id, name=f"{prefix}知识库")
    db.add(base)
    db.flush()
    doc = KnowledgeDocument(
        knowledge_base_id=base.id,
        uploader_id=owner_id,
        filename=f"{prefix}搭配指南.txt",
        file_type="txt",
        storage_path=f"/tmp/{prefix}-guide.txt",
        status="indexed",
        source_kind="recommendation_guide",
    )
    db.add(doc)
    db.flush()
    chunk_text = f"{prefix}搭配建议：{prefix}适合与红酒、土豆和意面搭配。"
    db.add(
        KnowledgeChunk(
            knowledge_base_id=base.id,
            document_id=doc.id,
            position=0,
            content=chunk_text,
        )
    )
    first = Product(owner_id=owner_id, source_key=f"{prefix}-a", name=prefix, category="肉类")
    second = Product(
        owner_id=owner_id, source_key=f"{prefix}-b", name="红酒", category="酒饮"
    )
    db.add_all([first, second])
    db.flush()
    rule = AssociationRule(
        owner_id=owner_id,
        import_id=1,
        antecedent_product_id=first.id,
        consequent_product_id=second.id,
        cooccurrence_count=12,
        support=0.6,
        confidence=0.8,
        lift=1.9,
        fingerprint=prefix * 32,
    )
    db.add(rule)
    db.commit()
    return {
        "base_id": base.id,
        "doc_id": doc.id,
        "chunk_text": chunk_text,
        "rule_id": rule.id,
    }


class _WorkingVectorIndexer:
    class _Store:
        async def delete_document(self, document_id):
            return None

    def __init__(self):
        self.store = self._Store()
        self.index_calls: list[dict] = []

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)


class _FailingVectorIndexer:
    class _Store:
        async def delete_document(self, document_id):
            return None

    def __init__(self):
        self.store = self._Store()

    async def index(self, **kwargs):
        raise RuntimeError("vector backend down")


def test_owner_scope_operator_sees_merchant_data(tmp_path: Path):
    """operator 通过组织成员关系代理商家数据：knowledge 与 commerce 均可见。"""

    async def scenario():
        database = _database(tmp_path, "owner-scope.db")
        with database.session_factory() as db:
            owner = User(username="merchant-a", password_hash="hash", role="user")
            operator = User(
                username="operator-b", password_hash="hash", role="operator"
            )
            db.add_all([owner, operator])
            db.flush()
            org = Organization(name="商家A组织", owner_user_id=owner.id)
            db.add(org)
            db.flush()
            db.add(
                OrganizationMember(
                    org_id=org.id, user_id=operator.id, role="operator"
                )
            )
            # 无关商家的数据：operator 不得看到
            foreign = User(username="merchant-c", password_hash="hash", role="user")
            db.add(foreign)
            db.flush()
            _seed_merchant(db, owner.id, "牛肉")
            _seed_merchant(db, foreign.id, "秘密")
            db.commit()

            # 1) 数据归属解析：operator 的业务数据 owner 是组织 owner（商家 A）
            assert resolve_owner(db, operator) == owner.id
            assert resolve_owner(db, owner) == owner.id

            # 2) 工具直接断言：owner_id=A 时 knowledge/commerce 都能命中 A 的数据
            registry = build_tool_registry(None)
            context_a = ToolContext(db, owner.id)
            kb_hit = await registry.execute(
                "knowledge.search", {"query": "牛肉搭配建议", "limit": 6}, context_a
            )
            assert kb_hit.status == "success"
            assert any(
                "牛肉适合与红酒、土豆和意面搭配" in item.content
                for item in kb_hit.evidence
            )
            assert kb_hit.diagnostics["ownerId"] == owner.id
            rule_hit = await registry.execute(
                "commerce.search_association_rules",
                {"query": "牛肉", "limit": 6},
                context_a,
            )
            assert rule_hit.status == "success"
            assert any(
                item.metadata["factType"] == "association_rule"
                for item in rule_hit.evidence
            )
            # 用 operator 自己的 id 当 owner → 看不到商家数据（无隐式代理）
            context_b = ToolContext(db, operator.id)
            no_kb = await registry.execute(
                "knowledge.search", {"query": "牛肉搭配建议", "limit": 6}, context_b
            )
            assert no_kb.evidence == []

            # 3) 全链路：operator 发问，agentic 以 data_owner_id=商家 A 查询
            coordinator = AgenticRagCoordinator(None, None, max_steps=2)
            result = await coordinator.run(
                db,
                actor_user_id=operator.id,
                data_owner_id=owner.id,
                question="牛肉搭配建议",
            )
            assert any(
                item.channel == "knowledge.search"
                and "牛肉适合与红酒、土豆和意面搭配" in item.content
                for item in result.results
            )
            # 无关商家数据不泄漏
            assert all("秘密" not in item.content for item in result.results)
            # 知识库推荐证据放行且带 caveat
            assert result.terminal_state == "grounded"
            assert "知识库建议" in result.review_details.summary

    asyncio.run(scenario())


def test_cross_organization_knowledge_base_rejected(tmp_path: Path):
    """B 指定 C 商家的 knowledgeBaseId → prepare 抛 403，不跨商家检索。"""

    async def scenario():
        database = _database(tmp_path, "cross-org.db")
        with database.session_factory() as db:
            owner = User(username="merchant-a", password_hash="hash", role="user")
            operator = User(
                username="operator-b", password_hash="hash", role="operator"
            )
            foreign = User(username="merchant-c", password_hash="hash", role="user")
            db.add_all([owner, operator, foreign])
            db.flush()
            org = Organization(name="商家A组织", owner_user_id=owner.id)
            db.add(org)
            db.flush()
            db.add(
                OrganizationMember(
                    org_id=org.id, user_id=operator.id, role="operator"
                )
            )
            ours = _seed_merchant(db, owner.id, "牛肉")
            theirs = _seed_merchant(db, foreign.id, "秘密")
            db.commit()

            service = RagChatService(
                model_router=None,
                conversations=ConversationService(),
                retrieval=None,
                agentic=None,
            )
            data_owner_id = resolve_owner(db, operator)
            assert data_owner_id == owner.id

            trace = service.traces.start(
                db, user_id=operator.id, query="查询别人家的知识库"
            )
            with pytest.raises(AppError) as excinfo:
                await service.prepare(
                    db,
                    actor_user_id=operator.id,
                    data_owner_id=data_owner_id,
                    request=ChatRequest(
                        question="查询别人家的知识库",
                        knowledge_base_ids=[theirs["base_id"]],
                        rag_enabled=False,
                    ),
                    trace=trace,
                )
            assert excinfo.value.code == "KNOWLEDGE_BASE_FORBIDDEN"
            assert excinfo.value.status_code == 403

            # 自己的知识库 ID 放行；空列表（名下全部）也放行
            allowed = await service.prepare(
                db,
                actor_user_id=operator.id,
                data_owner_id=data_owner_id,
                request=ChatRequest(
                    question="查询自家知识库",
                    knowledge_base_ids=[ours["base_id"]],
                    rag_enabled=False,
                ),
                trace=service.traces.start(db, user_id=operator.id, query="查询自家"),
            )
            assert allowed.conversation_id
            empty_ok = await service.prepare(
                db,
                actor_user_id=operator.id,
                data_owner_id=data_owner_id,
                request=ChatRequest(
                    question="查询全部知识库", knowledge_base_ids=[], rag_enabled=False
                ),
                trace=service.traces.start(db, user_id=operator.id, query="查询全部"),
            )
            assert empty_ok.conversation_id

    asyncio.run(scenario())


def test_ingest_vector_failure_keeps_keyword_searchable(tmp_path: Path):
    """向量索引失败 → 文档仍 indexed（关键词可搜）；成功/失败/parse 失败三路径。"""
    directory = tmp_path / "uploads"
    directory.mkdir()
    source = directory / "牛肉搭配指南.txt"
    source.write_text(
        "牛肉适合与红酒、土豆和意面搭配。牛肉也适合与西红柿同煮。",
        encoding="utf-8",
    )
    database = _database(tmp_path, "ingest-degrade.db")

    with database.session_factory() as db:
        owner = User(username="ingest-owner", password_hash="hash")
        db.add(owner)
        db.commit()
        db.refresh(owner)

        # 1) vector 索引失败 → status=indexed + vector_indexed=False + 可搜索
        failing = KnowledgeService(vector_indexer=_FailingVectorIndexer())
        base = failing.create_base(db, owner_id=owner.id, name="牛肉搭配知识库")
        document = failing.create_document(
            db,
            base_id=base.id,
            uploader_id=owner.id,
            owner_id=owner.id,
            filename="牛肉搭配指南.txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
        )
        ingested = failing.ingest_document(db, document.id)
        assert ingested.status == "indexed"
        assert ingested.vector_indexed is False
        assert "向量索引失败" in (ingested.error_message or "")
        chunks = list(
            db.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document.id
                )
            )
        )
        assert chunks

        channel = SqlKeywordSearchChannel(database)
        results = asyncio.run(
            channel.search(
                RetrievalRequest("牛肉搭配", metadata={"owner_id": owner.id})
            )
        )
        assert any(
            "牛肉适合与红酒、土豆和意面搭配" in item.content for item in results
        )
        # 失败文档的 factType 由 source_kind 推导（filename 含「指南」）
        assert all(item.metadata["factType"] == "recommendation" for item in results)

        # 2) vector 索引成功 → status=indexed + vector_indexed=True
        working = KnowledgeService(vector_indexer=_WorkingVectorIndexer())
        good = working.create_document(
            db,
            base_id=base.id,
            uploader_id=owner.id,
            owner_id=owner.id,
            filename="商品说明.txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
        )
        good_doc = working.ingest_document(db, good.id)
        assert good_doc.status == "indexed"
        assert good_doc.vector_indexed is True
        assert good_doc.error_message is None

        # 3) parse 失败（不支持的文件类型）→ status=failed
        broken = KnowledgeService(vector_indexer=_FailingVectorIndexer())
        unsupported = broken.create_document(
            db,
            base_id=base.id,
            uploader_id=owner.id,
            owner_id=owner.id,
            filename="神秘文件.xyz",
            storage_path=str(directory / "mystery.xyz"),
            file_size=1,
        )
        failed_doc = broken.ingest_document(db, unsupported.id)
        assert failed_doc.status == "failed"
        assert failed_doc.error_message


def test_knowledge_fact_type_by_source_kind(tmp_path: Path):
    """source_kind 各值 → metadata.factType 映射正确，不再全 policy。"""
    database = _database(tmp_path, "fact-type.db")
    with database.session_factory() as db:
        owner = User(username="fact-owner", password_hash="hash")
        db.add(owner)
        db.commit()
        base = KnowledgeBase(owner_id=owner.id, name="映射知识库")
        db.add(base)
        db.flush()
        kinds = [
            "policy",
            "sop",
            "product_knowledge",
            "recommendation_guide",
            "operations_guide",
            "general",
        ]
        expected = {
            "policy": "policy",
            "sop": "sop",
            "product_knowledge": "product_knowledge",
            "recommendation_guide": "recommendation",
            "operations_guide": "operations",
            "general": "general",
        }
        for index, kind in enumerate(kinds):
            document = KnowledgeDocument(
                knowledge_base_id=base.id,
                uploader_id=owner.id,
                filename=f"{kind}.txt",
                file_type="txt",
                storage_path=f"/tmp/{kind}.txt",
                status="indexed",
                source_kind=kind,
            )
            db.add(document)
            db.flush()
            db.add(
                KnowledgeChunk(
                    knowledge_base_id=base.id,
                    document_id=document.id,
                    position=0,
                    content=f"{kind} 相关知识内容",
                )
            )
        db.commit()

        channel = SqlKeywordSearchChannel(database)
        results = asyncio.run(
            channel.search(
                RetrievalRequest("相关知识", metadata={"owner_id": owner.id})
            )
        )
        assert len(results) == len(kinds)
        by_doc = {item.metadata["document_id"]: item for item in results}
        documents = list(
            db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id))
        )
        for document in documents:
            item = by_doc[document.id]
            assert item.metadata["sourceKind"] == document.source_kind
            assert item.metadata["factType"] == expected[document.source_kind]
            # _fact_type 直接消费 metadata.factType（不再默认 policy）
            assert AgenticRagCoordinator._fact_type(item) == expected[
                document.source_kind
            ]


def test_planner_combines_commerce_and_knowledge():
    """搭配/推荐类问题：fallback candidates 同时含 commerce 与 knowledge。"""
    coordinator = AgenticRagCoordinator(None, None)
    decision = coordinator._fallback_decision(
        "牛肉适合搭配哪些商品？给出推荐依据", [], ""
    )
    names = [call.name for call in decision.calls]
    assert "commerce.search_association_rules" in names
    assert "commerce.get_product_metrics" in names
    assert "knowledge.search" in names
    # 纯政策问题仍只走知识库
    policy = coordinator._fallback_decision("退货政策是什么", [], "")
    assert [call.name for call in policy.calls] == ["knowledge.search"]


def test_reviewer_accepts_knowledge_recommendation_with_caveat():
    """仅知识库推荐证据：无强要求词 → ready + caveat；带销售数据 → 不 ready。"""
    recommendation = SearchResult(
        id="1",
        content="牛肉适合与红酒、土豆和意面搭配",
        score=1.0,
        channel="knowledge.search",
        source="搭配指南",
        metadata={"factType": "recommendation"},
    )
    relaxed = AgenticRagCoordinator._review_evidence(
        "牛肉有什么搭配建议？", [recommendation], can_replan=True
    )
    assert relaxed.decision == "ready"
    assert "知识库建议" in relaxed.summary
    assert relaxed.missing_fields == ("association_rule",)

    strong = AgenticRagCoordinator._review_evidence(
        "牛肉搭配的销售数据如何？", [recommendation], can_replan=True
    )
    assert strong.decision == "replan"
    assert "销售数据" in strong.summary or "证据未覆盖" in strong.summary

    none_evidence = AgenticRagCoordinator._review_evidence(
        "牛肉有什么搭配建议？", [], can_replan=True
    )
    assert none_evidence.decision == "replan"


def test_knowledge_tool_all_channels_failed_is_failed_not_zero(tmp_path: Path):
    """全部检索通道失败 → 工具 status=failed（RETRIEVAL_FAILED），
    不显示为 0 evidence；Timeline 用户侧文案「知识检索暂时失败」。"""

    class BrokenEngine:
        async def retrieve(self, request):
            raise RetrievalError(
                "知识检索服务暂时不可用",
                {"channels": [{"name": "keyword", "error": "backend down"}]},
            )

    def scenario():
        database = _database(tmp_path, "retrieval-failed.db")
        with database.session_factory() as db:
            owner = User(username="fail-owner", password_hash="hash")
            db.add(owner)
            db.commit()
            registry = build_tool_registry(BrokenEngine())
            outcome = asyncio.run(
                registry.execute(
                    "knowledge.search",
                    {"query": "牛肉", "limit": 6},
                    ToolContext(db, owner.id),
                )
            )
            assert outcome.status == "failed"
            assert outcome.error_code == "RETRIEVAL_FAILED"
            assert outcome.evidence == []

            events: list[dict] = []

            async def sink(event):
                events.append(event)

            coordinator = AgenticRagCoordinator(None, BrokenEngine(), max_steps=1)
            result = asyncio.run(
                coordinator.run(
                    db,
                    actor_user_id=owner.id,
                    data_owner_id=owner.id,
                    question="退货政策是什么",
                    progress_sink=sink,
                )
            )
            tool_failed = [
                item
                for item in events
                if item["phase"] == "tool" and item["status"] == "failed"
            ]
            assert tool_failed
            assert tool_failed[0]["tool"]["name"] == "knowledge.search"
            assert tool_failed[0]["detail"] == "知识检索暂时失败"
            assert result.terminal_state == "escalated"

    scenario()
