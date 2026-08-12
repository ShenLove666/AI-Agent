"""知识库管理 API 与 Chat 的 data_owner 数据域统一回归测试。

覆盖：
1. 知识库管理端点（create/list/documents/upload）按 resolve_owner 的商家
   data_owner 归属：组织成员 B 经真实 API 创建/列出知识库时归属组织 owner A；
   跨商家 base 一律拒绝（require_owned_base 抛错语义不变）。
2. create_document 拆分 uploader（操作者）与 owner（商家数据域）：B 上传 →
   uploader_id==B、base.owner_id==A；ingest 的向量索引按 base owner（A）归档。
3. migration 0012：owner 归错为成员 id 的 base 修复为组织 owner（幂等）；
   source_kind=general 旧文档按 service.infer_source_kind 同规则回填
   （含「指南」文件名 → recommendation_guide）。
4. prepare 的 retrieval 诊断：knowledge.search 多轮调用聚合为
   knowledgeSearchCalls 数组（按 plan 排序）+ lastKnowledgeSearch +
   knowledgeSearchTotalCount；reviewer 事实类型集合 presentFactTypes /
   requiredFactTypes / auxiliaryFactTypes 进入 trace attributes。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from alembic import command
from sqlalchemy import select

import app.application_core  # noqa: F401  (注册全部 ORM 模型)
from app.framework.database import Database
from app.framework.errors import AppError
from app.framework.migrations import build_alembic_config, upgrade_database
from app.modules.conversations.service import ConversationService
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.knowledge.service import KnowledgeService
from app.modules.rag.agentic import (
    AgentDecision,
    AgenticRun,
    EvidenceReview,
    ToolCallPlan,
)
from app.modules.rag.schemas import ChatRequest
from app.modules.rag.service import RagChatService
from app.modules.rag.trace_models import RagTraceNode
from app.modules.users.access import resolve_owner
from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.repository import UserRepository


def _database(tmp_path: Path, name: str = "data-owner.db") -> Database:
    database = Database(f"sqlite:///{tmp_path / name}")
    upgrade_database(database)
    return database


class _WorkingVectorIndexer:
    class _Store:
        async def delete_document(self, document_id):
            return None

    def __init__(self):
        self.store = self._Store()
        self.index_calls: list[dict] = []

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)


def _seed_org(db, *, owner: User, member: User) -> Organization:
    org = Organization(name="商家组织", owner_user_id=owner.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(org_id=org.id, user_id=member.id, role="operator"))
    # 组织 owner 同时也是成员（与 demo seed 行为一致）
    db.add(OrganizationMember(org_id=org.id, user_id=owner.id, role="owner"))
    db.commit()
    return org


def test_knowledge_api_uses_data_owner(tmp_path: Path):
    """真实 API：组织成员 B 创建/列出知识库归属组织 owner A；跨商家拒绝。"""
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/api.db"
            os.environ["UPLOAD_DIR"] = f"{directory}/uploads"
            from app.application import create_app

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    for username in ("merchant-a", "member-b", "merchant-c"):
                        await client.post(
                            "/api/v1/auth/register",
                            json={"username": username, "password": "password123"},
                        )
                    # 角色与组织关系（无 org 管理 API，直接写库）：
                    # A=商家 owner（user），B=组织成员（admin 以便通过
                    # knowledge.manage 权限门禁；operator 角色按权限设计
                    # 无 knowledge.manage，其 data_owner 拆分在 service 层测）。
                    # C=无关商家（admin 同样只为过权限门禁，无组织归属）。
                    with app.state.container.database.session_factory() as db:
                        repo = UserRepository()
                        owner_a = repo.get_by_username(db, "merchant-a")
                        member_b = repo.get_by_username(db, "member-b")
                        foreign_c = repo.get_by_username(db, "merchant-c")
                        owner_a.role = "user"
                        member_b.role = "admin"
                        foreign_c.role = "admin"
                        db.flush()
                        _seed_org(db, owner=owner_a, member=member_b)
                        db.commit()
                        assert resolve_owner(db, member_b) == owner_a.id
                        assert resolve_owner(db, foreign_c) == foreign_c.id

                    async def login(username: str) -> dict:
                        response = await client.post(
                            "/api/v1/auth/login",
                            json={"username": username, "password": "password123"},
                        )
                        return {
                            "Authorization": (
                                "Bearer "
                                f"{response.json()['data']['access_token']}"
                            )
                        }

                    headers_b = await login("member-b")
                    headers_c = await login("merchant-c")

                    # 1) B 创建知识库 → owner_id == 组织 owner A（不是 B）
                    created = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "B 创建的商家知识库"},
                        headers=headers_b,
                    )
                    assert created.status_code == 201
                    b_base_id = created.json()["data"]["id"]
                    with app.state.container.database.session_factory() as db:
                        base = db.get(KnowledgeBase, b_base_id)
                        assert base.owner_id == db.scalar(
                            select(User.id).where(User.username == "merchant-a")
                        )

                    # 2) B 列表可见 A 名下的 base（按 data_owner=A 查询）
                    listed = await client.get(
                        "/api/v1/knowledge-bases", headers=headers_b
                    )
                    names = [item["name"] for item in listed.json()["data"]]
                    assert "B 创建的商家知识库" in names

                    # 3) C 创建自己的 base：B 列表看不到，B 访问其文档 404
                    foreign = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "C 的私有知识库"},
                        headers=headers_c,
                    )
                    c_base_id = foreign.json()["data"]["id"]
                    listed_after = await client.get(
                        "/api/v1/knowledge-bases", headers=headers_b
                    )
                    names_after = [item["name"] for item in listed_after.json()["data"]]
                    assert "C 的私有知识库" not in names_after
                    forbidden = await client.get(
                        f"/api/v1/knowledge-bases/{c_base_id}/documents",
                        headers=headers_b,
                    )
                    assert forbidden.status_code == 404
                    assert forbidden.json()["error"]["code"] == (
                        "KNOWLEDGE_BASE_NOT_FOUND"
                    )

                    # 4) B 向自家 base 上传文档：uploader==B、base owner==A
                    uploaded = await client.post(
                        f"/api/v1/knowledge-bases/{b_base_id}/documents",
                        files={
                            "file": (
                                "搭配指南.txt",
                                "牛肉适合与红酒、土豆和意面搭配。",
                                "text/plain",
                            )
                        },
                        headers=headers_b,
                    )
                    assert uploaded.status_code == 202
                    with app.state.container.database.session_factory() as db:
                        document = db.scalar(
                            select(KnowledgeDocument).where(
                                KnowledgeDocument.knowledge_base_id == b_base_id
                            )
                        )
                        assert document is not None
                        assert document.uploader_id == db.scalar(
                            select(User.id).where(User.username == "member-b")
                        )
                        assert db.get(KnowledgeBase, b_base_id).owner_id == db.scalar(
                            select(User.id).where(User.username == "merchant-a")
                        )

                    # 5) service 层：require_owned_base 跨商家抛错（语义不变）
                    with app.state.container.database.session_factory() as db:
                        member_b_user = db.scalar(
                            select(User).where(User.username == "member-b")
                        )
                        with pytest.raises(AppError) as excinfo:
                            app.state.container.knowledge.require_owned_base(
                                db, c_base_id, resolve_owner(db, member_b_user)
                            )
                        assert excinfo.value.code == "KNOWLEDGE_BASE_NOT_FOUND"

    asyncio.run(scenario())


def test_create_document_splits_uploader_and_owner(tmp_path: Path):
    """B（组织成员/operator）上传文档：uploader==B、base owner==A，
    ingest 的向量索引 owner 用 A。"""
    directory = tmp_path / "uploads"
    directory.mkdir()
    source = directory / "牛肉搭配指南.txt"
    source.write_text(
        "牛肉适合与红酒、土豆和意面搭配。", encoding="utf-8"
    )
    database = _database(tmp_path, "split-owner.db")

    with database.session_factory() as db:
        owner_a = User(username="merchant-a", password_hash="hash", role="user")
        member_b = User(username="member-b", password_hash="hash", role="operator")
        foreign_c = User(username="merchant-c", password_hash="hash", role="user")
        db.add_all([owner_a, member_b, foreign_c])
        db.flush()
        _seed_org(db, owner=owner_a, member=member_b)
        c_base = KnowledgeBase(owner_id=foreign_c.id, name="C 的知识库")
        db.add(c_base)
        db.commit()

        service = KnowledgeService(vector_indexer=_WorkingVectorIndexer())
        base = service.create_base(db, owner_id=owner_a.id, name="A 搭配知识库")
        data_owner_b = resolve_owner(db, member_b)
        assert data_owner_b == owner_a.id

        document = service.create_document(
            db,
            base_id=base.id,
            uploader_id=member_b.id,
            owner_id=data_owner_b,
            filename="牛肉搭配指南.txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
        )
        ingested = service.ingest_document(db, document.id)
        assert ingested.uploader_id == member_b.id
        assert ingested.vector_indexed is True
        assert db.get(KnowledgeBase, base.id).owner_id == owner_a.id
        # 向量索引按商家数据 owner（A）归档，而非上传者（B）
        assert service.vector_indexer.index_calls[0]["owner_id"] == owner_a.id

        # 跨商家：B 对 C 的 base 上传 → require_owned_base 抛错
        with pytest.raises(AppError) as excinfo:
            service.create_document(
                db,
                base_id=c_base.id,
                uploader_id=member_b.id,
                owner_id=data_owner_b,
                filename="越权.txt",
                storage_path=str(source),
                file_size=1,
            )
        assert excinfo.value.code == "KNOWLEDGE_BASE_NOT_FOUND"


def test_migration_0012_repairs_owner_and_backfills_source_kind(tmp_path: Path):
    """0012 迁移：成员 id 归属的 base 修复为组织 owner；source_kind 回填；
    幂等可重复执行。"""
    database = Database(f"sqlite:///{tmp_path / 'repair.db'}")
    config = build_alembic_config(
        database.engine.url.render_as_string(hide_password=False)
    )
    # 先升到 0011（0012 尚未执行），构造「旧数据」
    command.upgrade(config, "0011_knowledge_source_kind")
    with database.session_factory() as db:
        owner_a = User(username="merchant-a", password_hash="hash", role="user")
        member_b = User(username="member-b", password_hash="hash", role="operator")
        foreign_c = User(username="merchant-c", password_hash="hash", role="user")
        db.add_all([owner_a, member_b, foreign_c])
        db.flush()
        _seed_org(db, owner=owner_a, member=member_b)
        # 归属错误：owner 是组织成员 id 而非组织 owner
        base_member = KnowledgeBase(owner_id=member_b.id, name="退货政策知识库")
        # 搭配库：base 名含「搭配」（recommendation 词），不含 policy/product 词
        base_guide = KnowledgeBase(owner_id=member_b.id, name="搭配知识库")
        base_owner = KnowledgeBase(owner_id=owner_a.id, name="商品说明库")
        base_foreign = KnowledgeBase(owner_id=foreign_c.id, name="别家规则库")
        # 无任何规则词的知识库：文档应保持 general
        base_plain = KnowledgeBase(owner_id=owner_a.id, name="公共资料库")
        db.add_all([base_member, base_guide, base_owner, base_foreign, base_plain])
        db.flush()
        db.add_all(
            [
                KnowledgeDocument(
                    knowledge_base_id=base_member.id,
                    uploader_id=member_b.id,
                    filename="七日退货政策.txt",
                    file_type="txt",
                    storage_path="/tmp/1.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_member.id,
                    uploader_id=member_b.id,
                    filename="一般资料.txt",
                    file_type="txt",
                    storage_path="/tmp/2.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_guide.id,
                    uploader_id=member_b.id,
                    filename="牛肉搭配指南.txt",
                    file_type="txt",
                    storage_path="/tmp/3.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_owner.id,
                    uploader_id=owner_a.id,
                    filename="商品说明.md",
                    file_type="md",
                    storage_path="/tmp/4.md",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_owner.id,
                    uploader_id=owner_a.id,
                    filename="已标注政策.txt",
                    file_type="txt",
                    storage_path="/tmp/5.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="policy",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_foreign.id,
                    uploader_id=foreign_c.id,
                    filename="退款规则.txt",
                    file_type="txt",
                    storage_path="/tmp/6.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
                KnowledgeDocument(
                    knowledge_base_id=base_plain.id,
                    uploader_id=owner_a.id,
                    filename="普通文档.txt",
                    file_type="txt",
                    storage_path="/tmp/7.txt",
                    file_size=1,
                    status="indexed",
                    source_kind="general",
                ),
            ]
        )
        db.commit()
        snapshot = {
            "base_member": base_member.id,
            "base_owner": base_owner.id,
            "base_foreign": base_foreign.id,
        }

    def assert_repaired(db) -> None:
        with db.session_factory() as session:
            assert (
                session.get(KnowledgeBase, snapshot["base_member"]).owner_id
                == session.scalar(select(User.id).where(User.username == "merchant-a"))
            )
            # 已正确的归属不动
            assert (
                session.get(KnowledgeBase, snapshot["base_owner"]).owner_id
                == session.scalar(select(User.id).where(User.username == "merchant-a"))
            )
            # 无关商家（非成员）不动
            assert (
                session.get(KnowledgeBase, snapshot["base_foreign"]).owner_id
                == session.scalar(select(User.id).where(User.username == "merchant-c"))
            )
            by_name = {
                document.filename: document.source_kind
                for document in session.scalars(select(KnowledgeDocument))
            }
            # 规则与 service.infer_source_kind 一致：
            # policy 词（filename 或 base 名）→ policy；「指南」→ recommendation_guide
            assert by_name["七日退货政策.txt"] == "policy"
            assert by_name["一般资料.txt"] == "policy"  # 命中 base 名「退货政策」
            assert by_name["牛肉搭配指南.txt"] == "recommendation_guide"
            assert by_name["商品说明.md"] == "product_knowledge"
            assert by_name["退款规则.txt"] == "policy"
            # 无规则词 → 保持 general（默认分支）
            assert by_name["普通文档.txt"] == "general"
            # 非 general 的文档 guard 不动
            assert by_name["已标注政策.txt"] == "policy"

    # 执行 0012
    command.upgrade(config, "head")
    assert_repaired(database)
    # 幂等：降级再升级，0012 重复执行结果不变
    command.downgrade(config, "0011_knowledge_source_kind")
    command.upgrade(config, "head")
    assert_repaired(database)


class _FakeAgentic:
    def __init__(self, run_result: AgenticRun):
        self.run_result = run_result

    async def run(
        self,
        db,
        *,
        actor_user_id,
        data_owner_id,
        question,
        original_question=None,
        knowledge_base_ids=(),
        allowed_document_ids=None,
        progress_sink=None,
    ):
        return self.run_result


def _build_two_plan_run() -> AgenticRun:
    """两次 knowledge.search（plan 1 与 plan 2）的 agent 运行结果。"""
    steps = (
        {
            "agent": "planner",
            "plan": 1,
            "mode": "research",
            "tools": ["knowledge.search"],
            "calls": [ToolCallPlan(name="knowledge.search", arguments={"query": "q1"}).model_dump()],
            "rationale": "第一轮检索",
            "runtimeMode": "deterministic_fallback",
        },
        {
            "agent": "tools",
            "plan": 1,
            "executions": [
                {
                    "tool": "knowledge.search",
                    "status": "success",
                    "arguments": {"query": "q1", "limit": 6},
                    "diagnostics": {
                        "keywordCount": 1,
                        "vectorCandidateCount": 2,
                        "finalCount": 0,
                        "channelErrors": {},
                    },
                }
            ],
            "observations": 0,
            "toolCalls": 1,
        },
        {
            "agent": "evidence_reviewer",
            "plan": 1,
            "review": "replan: 证据未覆盖回答所需字段",
            "details": {"decision": "replan"},
            "evidence": 0,
        },
        {
            "agent": "planner",
            "plan": 2,
            "mode": "research",
            "tools": ["knowledge.search"],
            "calls": [ToolCallPlan(name="knowledge.search", arguments={"query": "q2"}).model_dump()],
            "rationale": "补充检索",
            "runtimeMode": "deterministic_fallback",
        },
        {
            "agent": "tools",
            "plan": 2,
            "executions": [
                {
                    "tool": "knowledge.search",
                    "status": "success",
                    "arguments": {"query": "q2", "limit": 6},
                    "diagnostics": {
                        "keywordCount": 3,
                        "vectorCandidateCount": 0,
                        "vectorError": "vector backend down",
                        "vectorEnabled": True,
                        "finalCount": 4,
                        "channelErrors": {"vector": "vector backend down"},
                    },
                },
                {
                    "tool": "commerce.get_product_metrics",
                    "status": "success",
                    "arguments": {"query": "q2", "limit": 6},
                    "diagnostics": {"finalCount": 2, "channelErrors": {}},
                },
            ],
            "observations": 4,
            "toolCalls": 2,
        },
        {
            "agent": "evidence_reviewer",
            "plan": 2,
            "review": "ready: 证据相关、覆盖完整且满足风险要求",
            "details": {"decision": "ready"},
            "evidence": 4,
        },
    )
    decision = AgentDecision(
        "research",
        (ToolCallPlan(name="knowledge.search", arguments={"query": "q2"}),),
        "补充检索",
        "deterministic_fallback",
    )
    review_details = EvidenceReview(
        intent="policy_lookup",
        relevance=1.0,
        coverage=0.5,
        authority_sufficient=True,
        risk="medium",
        decision="ready",
        summary="证据相关、覆盖完整且满足风险要求",
        present_fact_types=("policy",),
        required_fact_types=("order", "policy"),
        auxiliary_fact_types=(),
    )
    return AgenticRun(
        decision,
        (),
        "ready: 证据相关、覆盖完整且满足风险要求",
        review_details,
        steps,
        "grounded",
        "deterministic_fallback",
    )


def test_prepare_diagnostics_aggregates_knowledge_search_calls(tmp_path: Path):
    """prepare 的 retrieval trace 聚合两次 knowledge.search：
    knowledgeSearchCalls 长度 2、按 plan 排序、lastKnowledgeSearch 是 plan 2；
    并暴露 reviewer 的 presentFactTypes/requiredFactTypes/auxiliaryFactTypes。"""
    async def scenario():
        database = _database(tmp_path, "diag-aggregate.db")
        service = RagChatService(
            model_router=None,
            conversations=ConversationService(),
            retrieval=None,
            agentic=_FakeAgentic(_build_two_plan_run()),
        )
        with database.session_factory() as db:
            owner = User(username="diag-owner", password_hash="hash", role="user")
            db.add(owner)
            db.commit()
            trace = service.traces.start(
                db, user_id=owner.id, query="退货政策依据是什么"
            )
            await service.prepare(
                db,
                actor_user_id=owner.id,
                data_owner_id=owner.id,
                request=ChatRequest(
                    question="退货政策依据是什么", rag_enabled=True
                ),
                trace=trace,
            )
            node = db.scalar(
                select(RagTraceNode).where(
                    RagTraceNode.run_id == trace.run.id,
                    RagTraceNode.name == "retrieval",
                )
            )
            assert node is not None
            attributes = json.loads(node.attributes_json)

        calls = attributes["knowledgeSearchCalls"]
        assert isinstance(calls, list)
        assert len(calls) == 2
        assert [call["plan"] for call in calls] == [1, 2]
        assert calls[0]["query"] == "q1"
        assert calls[0]["keywordCount"] == 1
        assert calls[0]["vectorCount"] == 2
        assert calls[0]["finalCount"] == 0
        assert calls[0]["channelErrors"] == {}
        assert calls[1]["query"] == "q2"
        assert calls[1]["keywordCount"] == 3
        assert calls[1]["vectorCount"] == 0
        assert calls[1]["finalCount"] == 4
        assert calls[1]["channelErrors"] == {"vector": "vector backend down"}
        # lastKnowledgeSearch = 最后一次调用（plan 2）
        assert attributes["lastKnowledgeSearch"] == calls[1]
        assert attributes["knowledgeSearchTotalCount"] == 2
        # reviewer 事实类型集合（区分 0 results 与 evidence type 不满足）
        assert attributes["presentFactTypes"] == ["policy"]
        assert attributes["requiredFactTypes"] == ["order", "policy"]
        assert attributes["auxiliaryFactTypes"] == []
        # 兼容保留：标量取第一次 knowledge.search 诊断
        assert attributes["keywordCandidateCount"] == 1
        assert attributes["postprocessorFinalCount"] == 0

    asyncio.run(scenario())
