from __future__ import annotations

import asyncio
import os
import tempfile

import httpx

from app.infra_ai.contracts import ChatRequest as ModelChatRequest, ModelStreamChunk
from app.modules.rag.schemas import ChatRequest as RagChatRequest


class FakeChatRouter:
    def __init__(self):
        self.last_request: ModelChatRequest | None = None
        self.complete_calls = 0

    async def complete(self, request: ModelChatRequest) -> str:
        self.last_request = request
        self.complete_calls += 1
        return "报关流程包括申报、查验、征税和放行。"

    async def stream(self, request: ModelChatRequest, cancel_event=None):
        self.last_request = request
        if request.metadata.get("deep_thinking"):
            yield ModelStreamChunk("thinking", "正在核对知识库证据")
        for token in ("报关流程", "包括四个环节。"):
            yield ModelStreamChunk("response", token)


def test_rag_chat_returns_citations_and_persists_messages():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/test.db"
            os.environ["UPLOAD_DIR"] = f"{directory}/uploads"
            from app.application import create_app

            app = create_app()
            fake_router = FakeChatRouter()
            app.state.container.chat.model_router = fake_router
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "raguser", "password": "password123"},
                    )
                    from app.modules.users.models import User as _User
                    from app.modules.users.repository import UserRepository as _UserRepo
                    with app.state.container.database.session_factory() as _db:
                        for _uname in ("raguser",):
                            _u = _UserRepo().get_by_username(_db, _uname)
                            _u.role = "admin"
                        _db.commit()
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "raguser", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    base = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "业务知识"},
                        headers=headers,
                    )
                    base_id = base.json()["data"]["id"]
                    await client.post(
                        f"/api/v1/knowledge-bases/{base_id}/documents",
                        files={"file": ("customs.txt", "报关流程包括申报、查验、征税和放行。")},
                        headers=headers,
                    )

                    chat = await client.post(
                        "/api/v1/chat",
                        json={
                            "question": "报关流程是什么？",
                            "request_id": "request-rag-001",
                            "deep_thinking": True,
                        },
                        headers=headers,
                    )
                    assert chat.status_code == 200
                    data = chat.json()["data"]
                    assert data["citations"][0]["source"] == "customs.txt"
                    assert "可用资料" in fake_router.last_request.messages[-1].content
                    assert fake_router.last_request.metadata["deep_thinking"] is True

                    malformed_scope = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "非法范围不能退化为全部知识库",
                            "requestId": "request-invalid-scope-001",
                            "knowledgeBaseIds": [base_id, "abc"],
                        },
                        headers=headers,
                    )
                    assert malformed_scope.status_code == 422

                    legacy_get = await client.get(
                        "/api/v1/rag/v3/chat",
                        params={"question": "问题不应出现在 URL"},
                        headers=headers,
                    )
                    assert legacy_get.status_code == 404
                    assert fake_router.last_request.metadata["requested_mode"] == "thinking"

                    replay = await client.post(
                        "/api/v1/chat",
                        json={
                            "question": "报关流程是什么？",
                            "request_id": "request-rag-001",
                            "deep_thinking": True,
                        },
                        headers=headers,
                    )
                    assert replay.status_code == 200
                    assert replay.json()["data"]["answer"] == data["answer"]
                    assert fake_router.complete_calls == 1

                    other_base = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "其他知识"},
                        headers=headers,
                    )
                    other_base_id = other_base.json()["data"]["id"]
                    await client.post(
                        f"/api/v1/knowledge-bases/{other_base_id}/documents",
                        files={"file": ("other.txt", "报关流程属于另一知识库。")},
                        headers=headers,
                    )
                    scoped_chat = await client.post(
                        "/api/v1/chat",
                        json={
                            "question": "报关流程",
                            "request_id": "request-scope-keyword-001",
                            "knowledge_base_ids": [base_id],
                        },
                        headers=headers,
                    )
                    assert scoped_chat.status_code == 200
                    scoped_citations = scoped_chat.json()["data"]["citations"]
                    assert scoped_citations
                    assert {
                        item["metadata"]["knowledge_base_id"] for item in scoped_citations
                    } == {base_id}

                    messages = await client.get(
                        f"/api/v1/conversations/{data['conversation_id']}/messages",
                        headers=headers,
                    )
                    roles = [item["role"] for item in messages.json()["data"]]
                    assert roles == ["user", "assistant"]

                    streamed = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "请深入分析报关流程",
                            "requestId": "request-rag-stream-001",
                            "deepThinking": True,
                        },
                        headers=headers,
                    )
                    assert streamed.status_code == 200
                    assert '"type": "think"' in streamed.text
                    assert fake_router.last_request.metadata["deep_thinking"] is True

                    from sqlalchemy import select
                    from app.modules.conversations.models import Message

                    with app.state.container.database.session_factory() as db:
                        latest = db.scalar(
                            select(Message)
                            .where(Message.role == "assistant")
                            .order_by(Message.id.desc())
                        )
                        assert latest.thinking_content == "正在核对知识库证据"

    asyncio.run(scenario())


def test_cancelled_request_is_not_cached_and_abnormal_history_is_filtered():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/cancelled.db"
            from app.application import create_app

            app = create_app()
            fake_router = FakeChatRouter()
            app.state.container.chat.model_router = fake_router
            async with app.router.lifespan_context(app):
                with app.state.container.database.session_factory() as db:
                    from app.modules.users.models import User
                    from app.modules.users.service import AuthService

                    user = User(
                        username="cancel-user",
                        password_hash=AuthService(None).passwords.hash("password123"),
                    )
                    db.add(user)
                    db.commit()
                    db.refresh(user)

                    request = RagChatRequest(
                        question="测试取消缓存",
                        request_id="request-cancelled-001",
                        rag_enabled=False,
                    )
                    cancelled = asyncio.Event()
                    cancelled.set()
                    first_events = [
                        event
                        async for event in app.state.container.chat.stream(
                            db, user.id, user.id, request, cancelled
                        )
                    ]
                    assert first_events[-1]["type"] == "cancelled"

                    from sqlalchemy import select
                    from app.modules.conversations.models import ChatRequestRun, Message

                    run = db.scalar(
                        select(ChatRequestRun).where(
                            ChatRequestRun.request_id == "request-cancelled-001"
                        )
                    )
                    assert run.status == "cancelled"
                    assert db.get(Message, run.assistant_message_id).message_status == "INTERRUPTED"

                    second_events = [
                        event
                        async for event in app.state.container.chat.stream(
                            db, user.id, user.id, request, asyncio.Event()
                        )
                    ]
                    assert second_events[-1]["type"] == "done"
                    db.refresh(run)
                    assert run.status == "completed"

                    app.state.container.conversations.add_message(
                        db,
                        conversation_id=run.conversation_id,
                        user_id=user.id,
                        role="assistant",
                        content="不应进入下一轮的错误半截回答",
                        message_status="ERROR",
                    )
                    await app.state.container.chat.complete(
                        db,
                        user.id,
                        user.id,
                        RagChatRequest(
                            question="下一轮问题",
                            conversation_id=run.conversation_id,
                            request_id="request-after-error-001",
                            rag_enabled=False,
                        ),
                    )
                    prompt_contents = [item.content for item in fake_router.last_request.messages]
                    assert "不应进入下一轮的错误半截回答" not in prompt_contents

    asyncio.run(scenario())


def test_failed_request_retry_does_not_duplicate_question_in_prompt():
    class FailOnceRouter:
        def __init__(self):
            self.calls = 0
            self.last_request = None

        async def complete(self, request: ModelChatRequest) -> str:
            self.calls += 1
            self.last_request = request
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return "重试成功"

        async def stream(self, request: ModelChatRequest, cancel_event=None):
            yield ModelStreamChunk("response", "unused")

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/retry.db"
            from app.application import create_app

            app = create_app()
            router = FailOnceRouter()
            app.state.container.chat.model_router = router
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "retryuser", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "retryuser", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    payload = {
                        "question": "同一个问题只应出现一次",
                        "request_id": "request-retry-001",
                        "rag_enabled": False,
                    }
                    first = await client.post("/api/v1/chat", json=payload, headers=headers)
                    assert first.status_code == 500
                    second = await client.post("/api/v1/chat", json=payload, headers=headers)
                    assert second.status_code == 200
                    user_prompts = [
                        item.content for item in router.last_request.messages if item.role == "user"
                    ]
                    assert user_prompts == ["同一个问题只应出现一次"]

                    conflict = await client.post(
                        "/api/v1/chat",
                        json={**payload, "question": "换成另一个问题"},
                        headers=headers,
                    )
                    assert conflict.status_code == 409
                    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

                    scope_conflict = await client.post(
                        "/api/v1/chat",
                        json={**payload, "knowledge_base_ids": [1]},
                        headers=headers,
                    )
                    assert scope_conflict.status_code == 409
                    assert scope_conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    asyncio.run(scenario())
