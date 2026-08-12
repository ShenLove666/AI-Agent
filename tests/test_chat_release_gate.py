"""聊天侧知识发布门禁：开启后 agentic 仅获得已发布并激活版本内的文档白名单。"""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

from app.infra_ai.contracts import ChatRequest as ModelChatRequest, ModelStreamChunk
from app.modules.rag.schemas import ChatRequest as RagChatRequest


class _ResearchIntentRouter:
    """强制 research 意图（复用 test_rag_chat_flow 的注入模式）。"""

    async def classify(self, question, history=None):
        from app.modules.rag.intent_router import IntentDecision

        return IntentDecision("research", "测试固定 research")


class _FakeChatRouter:
    async def complete(self, request: ModelChatRequest) -> str:
        return "已答复。"

    async def stream(self, request: ModelChatRequest, cancel_event=None):
        yield ModelStreamChunk("response", "已答复。")


class _RecordingAgentic:
    """记录每次 run() 收到的 kwargs，返回固定 research 运行结果。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, db, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            decision=SimpleNamespace(mode="research", tools=(), rationale=""),
            results=(),
            review="pass",
            review_details=None,
            steps=(),
            terminal_state="grounded",
            runtime_mode="model_backed",
        )


def test_chat_release_gate_controls_allowed_document_ids():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/gate.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            os.environ.pop("EMBED_MODEL_PATH", None)
            from app.application import create_app

            app = create_app()
            app.state.container.chat.model_router = _FakeChatRouter()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            recording = _RecordingAgentic()
            app.state.container.chat.agentic = recording
            async with app.router.lifespan_context(app):
                with app.state.container.database.session_factory() as db:
                    from app.modules.knowledge.models import (
                        KnowledgeBase,
                        KnowledgeDocument,
                    )
                    from app.modules.settings.models import RuntimeSetting
                    from app.modules.support.models import (
                        KnowledgeRelease,
                        KnowledgeReleaseDocument,
                    )
                    from app.modules.users.models import User
                    from app.modules.users.service import AuthService

                    user = User(
                        username="gate-user",
                        password_hash=AuthService(None).passwords.hash("password123"),
                        role="admin",
                    )
                    db.add(user)
                    db.flush()
                    base = KnowledgeBase(owner_id=user.id, name="门禁知识库")
                    db.add(base)
                    db.flush()
                    doc = KnowledgeDocument(
                        knowledge_base_id=base.id,
                        uploader_id=user.id,
                        filename="policy.md",
                        file_type="md",
                        storage_path="/tmp/policy.md",
                        status="indexed",
                    )
                    db.add(doc)
                    db.flush()
                    release = KnowledgeRelease(
                        owner_id=user.id,
                        version="v1",
                        title="已发布版本",
                        status="published",
                        content_hash="hash-v1",
                        is_active=True,
                    )
                    db.add(release)
                    db.flush()
                    db.add(
                        KnowledgeReleaseDocument(
                            release_id=release.id,
                            document_id=doc.id,
                            document_hash="hash-v1",
                            filename_snapshot="policy.md",
                        )
                    )
                    db.add(
                        RuntimeSetting(
                            key="chat_knowledge_release_gate", value_json='"true"'
                        )
                    )
                    db.commit()

                    request = RagChatRequest(
                        question="退货政策是什么？",
                        request_id="gate-on-001",
                        rag_enabled=True,
                    )
                    events = [
                        event
                        async for event in app.state.container.chat.stream(
                            db, user.id, user.id, request, asyncio.Event()
                        )
                    ]
                    assert events[-1]["type"] == "done"
                    # 开启：agentic 收到已发布版本内文档的白名单
                    assert recording.calls[-1]["allowed_document_ids"] == (doc.id,)

                    # 关闭：白名单为 None（不限制，历史行为）
                    gate = db.scalars(
                        __import__("sqlalchemy").select(RuntimeSetting).where(
                            RuntimeSetting.key == "chat_knowledge_release_gate"
                        )
                    ).one()
                    gate.value_json = '"false"'
                    db.commit()
                    request2 = RagChatRequest(
                        question="退货政策是什么？",
                        request_id="gate-off-001",
                        rag_enabled=True,
                    )
                    events2 = [
                        event
                        async for event in app.state.container.chat.stream(
                            db, user.id, user.id, request2, asyncio.Event()
                        )
                    ]
                    assert events2[-1]["type"] == "done"
                    assert recording.calls[-1]["allowed_document_ids"] is None

    asyncio.run(scenario())


def test_gate_without_active_release_yields_empty_allowlist():
    """门禁开启但无已发布版本 → 空元组：禁止检索任何知识文档。"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/gate2.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            os.environ.pop("EMBED_MODEL_PATH", None)
            from app.application import create_app

            app = create_app()
            app.state.container.chat.model_router = _FakeChatRouter()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            recording = _RecordingAgentic()
            app.state.container.chat.agentic = recording
            async with app.router.lifespan_context(app):
                with app.state.container.database.session_factory() as db:
                    from app.modules.settings.models import RuntimeSetting
                    from app.modules.users.models import User
                    from app.modules.users.service import AuthService

                    user = User(
                        username="gate2-user",
                        password_hash=AuthService(None).passwords.hash("password123"),
                        role="admin",
                    )
                    db.add(user)
                    db.flush()
                    db.add(
                        RuntimeSetting(
                            key="chat_knowledge_release_gate", value_json='"true"'
                        )
                    )
                    db.commit()

                    request = RagChatRequest(
                        question="退货政策是什么？",
                        request_id="gate-empty-001",
                        rag_enabled=True,
                    )
                    events = [
                        event
                        async for event in app.state.container.chat.stream(
                            db, user.id, user.id, request, asyncio.Event()
                        )
                    ]
                    assert events[-1]["type"] == "done"
                    assert recording.calls[-1]["allowed_document_ids"] == ()

    asyncio.run(scenario())
