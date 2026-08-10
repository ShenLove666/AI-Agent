from __future__ import annotations

import asyncio
import os
import tempfile

import httpx
from sqlalchemy import select

from app.infra_ai.contracts import ChatRequest as ModelChatRequest, ModelStreamChunk


class _ResearchIntentRouter:
    """强制 research 意图：避免意图分类器消费测试路由器的模型调用。"""

    async def classify(self, question, history=None):
        from app.modules.rag.intent_router import IntentDecision

        return IntentDecision("research", "测试固定 research")


class VersionedRouter:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[ModelChatRequest] = []

    async def complete(self, request: ModelChatRequest) -> str:
        self.calls += 1
        self.requests.append(request)
        return f"答案版本-{self.calls}"

    async def stream(self, request: ModelChatRequest, cancel_event=None):
        yield ModelStreamChunk("response", "流式答案")


def test_regeneration_versions_and_active_turn_history():
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/turns.db"
            from app.application import create_app

            app = create_app()
            router = VersionedRouter()
            app.state.container.chat.model_router = router
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "turn-user", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "turn-user", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    first = await client.post(
                        "/api/v1/chat",
                        json={
                            "question": "第一问",
                            "request_id": "conversation-turn-first",
                            "rag_enabled": False,
                        },
                        headers=headers,
                    )
                    assert first.status_code == 200, first.text
                    first_data = first.json()["data"]
                    assert first_data["version"] == 1

                    regenerated = await client.post(
                        f"/api/v1/conversations/turns/{first_data['turn_id']}/regenerate",
                        headers=headers,
                    )
                    assert regenerated.status_code == 200, regenerated.text
                    assert regenerated.json()["data"]["version"] == 2

                    history = await client.get(
                        f"/api/v1/conversations/{first_data['conversation_id']}/messages",
                        headers=headers,
                    )
                    rows = history.json()["data"]
                    assert [row["role"] for row in rows] == ["user", "assistant"]
                    assert rows[1]["content"] == "答案版本-2"
                    assert [item["version"] for item in rows[1]["answerVersions"]] == [1, 2]

                    second = await client.post(
                        "/api/v1/chat",
                        json={
                            "question": "第二问",
                            "conversation_id": first_data["conversation_id"],
                            "request_id": "conversation-turn-second",
                            "rag_enabled": False,
                        },
                        headers=headers,
                    )
                    assert second.status_code == 200, second.text
                    prompt = [(item.role, item.content) for item in router.requests[-1].messages]
                    assert ("assistant", "答案版本-2") in prompt
                    assert ("assistant", "答案版本-1") not in prompt

    asyncio.run(scenario())


def test_prepare_failure_finishes_trace():
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/trace.db"
            from app.application import create_app
            from app.modules.rag.schemas import ChatRequest
            from app.modules.rag.trace_models import RagTraceRun
            from app.modules.users.models import User
            from app.modules.users.service import AuthService

            app = create_app()
            app.state.container.database.create_schema()
            with app.state.container.database.session_factory() as db:
                user = User(
                    username="trace-user",
                    password_hash=AuthService(None).passwords.hash("password123"),
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                try:
                    await app.state.container.chat.complete(
                        db,
                        user.id,
                        user.id,
                        ChatRequest(
                            question="无效轮次",
                            request_id="prepare-failure-trace",
                            turn_id=999,
                            regenerate=True,
                            rag_enabled=False,
                        ),
                    )
                except Exception:
                    pass
                runs = list(db.scalars(select(RagTraceRun)))
                assert len(runs) == 1
                assert runs[0].status == "failed"
                assert runs[0].elapsed_ms is not None

    asyncio.run(scenario())
