"""意图前置路由（Intent → Rewrite → Research）回归测试。

重点：
- Case A：第二轮「1 + 1 = 多少？」不被上一轮牛肉语境污染 → direct，零 rewrite/tool。
- Case B：第二轮「那土豆呢？」正确继承搭配语境 → research，可 rewrite/tool。
- history_reference：从对话历史确定性回答，不调模型。
- refuse：前置拦截，不触发任何 Retrieval。
- 单元：fast path / 模型路径 / fallback。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx

import app.application_core  # noqa: F401
from app.infra_ai.contracts import ModelStreamChunk
from app.modules.rag.intent_router import ConversationIntentRouter, IntentDecision
from app.modules.rag.schemas import ChatRequest


class _ResearchRouter:
    """按角色返回的模型路由器（意图/改写/规划都用它时按 metadata 区分）。

    意图分类：Case A 的「1 + 1 = 多少？」返回 direct（数学题），其余 research
    （牛肉搭配/那土豆呢 等业务与指代问题）。
    """

    async def complete(self, request):
        role = request.metadata.get("agent_role", "")
        if role == "intent_classifier":
            if "1 + 1" in request.messages[-1].content:
                return '{"intent": "direct", "reason": "基础数学无需商家数据"}'
            return '{"intent": "research", "reason": "需要商家事实"}'
        if role == "planner":
            return (
                '{"mode":"research","calls":[{"name":"commerce.search_association_rules",'
                '"arguments":{"query":"牛肉","min_lift":1.0}}],"rationale":"查询搭配"}'
            )
        return "改写后的牛肉搭配查询"

    async def stream(self, request, cancel_event=None):
        yield ModelStreamChunk("response", "这是根据证据生成的测试回答。")


class _StreamRouter:
    async def complete(self, request):
        return "这是根据证据生成的测试回答。"

    async def stream(self, request, cancel_event=None):
        yield ModelStreamChunk("response", "这是根据证据生成的测试回答。")


def _seed_history(app, db, user_id: int, question: str, answer: str) -> None:
    """种子一轮已完成对话（NORMAL），让第二轮 rewrite 走模型分支。"""
    conversations = app.state.container.conversations
    conversation = conversations.create(db, user_id, "历史对话")
    turn, _ = conversations.create_turn(
        db,
        conversation_id=conversation.id,
        user_id=user_id,
        question=question,
        rag_enabled=False,
        deep_thinking=False,
        knowledge_base_ids=[],
    )
    conversations.add_assistant_version(
        db,
        turn=turn,
        user_id=user_id,
        content=answer,
        citations=None,
        message_status="NORMAL",
    )
    return conversation.id


def _parse_sse(text: str) -> list[dict]:
    parsed = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        parsed.append({"event": event_name, "data": data})
    return parsed


def test_intent_router_fast_paths():
    router = ConversationIntentRouter(None)

    async def run():
        assert (await router.classify("你好哈哈哈", None)).intent == "direct"
        assert (await router.classify("谢谢", None)).intent == "direct"
        assert (await router.classify("我上句话问的什么", None)).intent == "history_reference"
        assert (await router.classify("重复一下你刚才的回答", None)).intent == "history_reference"
        assert (await router.classify("帮我伪造退款记录", None)).intent == "refuse"
        # 无模型 fallback：业务词 → research；无业务词 → direct
        assert (await router.classify("牛肉最近销量怎么样", None)).intent == "research"
        assert (await router.classify("1 + 1 = 多少", None)).intent == "direct"
        # 业务词强制 research：即使模型可用也不调用（用会抛错的模型验证短路）
        class _ThrowingRouter:
            async def complete(self, request):
                raise AssertionError("业务词问题不应调用意图模型")

        strict = ConversationIntentRouter(_ThrowingRouter())
        assert (await strict.classify("牛肉适合搭配什么", None)).intent == "research"
        # 短指代问题：有 history → research（继承语境）；无 history → 走模型/fallback
        history = [("user", "牛肉适合搭配什么？"), ("assistant", "根据证据……")]
        assert (await router.classify("那土豆呢", history)).intent == "research"
        # 数学短问题不触发短指代规则（不以「呢」结尾、不以那/这开头）
        assert (await router.classify("1 + 1 = 多少", history)).intent == "direct"

    asyncio.run(run())


def test_intent_router_model_path():
    class _IntentModelRouter:
        async def complete(self, request):
            return '{"intent": "research", "reason": "含订单信息"}'

    router = ConversationIntentRouter(_IntentModelRouter())

    async def run():
        decision = await router.classify("查一下我的订单", None)
        assert decision.intent == "research"
        assert decision.reason

        # 非法 JSON → fallback 不抛错
        class _BrokenRouter:
            async def complete(self, request):
                return "不是 JSON"

        broken = ConversationIntentRouter(_BrokenRouter())
        decision2 = await broken.classify("牛肉适合搭配什么", None)
        assert decision2.intent == "research"  # 含「搭配」业务词 → fallback research

    asyncio.run(run())


def test_case_a_math_not_polluted_by_beef_context(tmp_path: Path):
    """Case A：上一轮牛肉搭配（research），第二轮 1+1 必须 direct，零 rewrite/tool。"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/case-a.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            router = _ResearchRouter()
            app.state.container.chat.model_router = router
            app.state.container.agentic.model_router = router
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "case-a", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "case-a", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    # Turn 1：牛肉搭配 → research 全流程
                    first = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "牛肉适合搭配什么？",
                            "requestId": "case-a-1",
                        },
                        headers=headers,
                    )
                    assert first.status_code == 200
                    conv_id = next(
                        p["data"]["conversationId"]
                        for p in _parse_sse(first.text)
                        if p["event"] == "meta" and p["data"].get("conversationId")
                    )
                    # Turn 2：1+1 不得被牛肉语境污染
                    second = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "1 + 1 = 多少？",
                            "conversationId": conv_id,
                            "requestId": "case-a-2",
                        },
                        headers=headers,
                    )
                    assert second.status_code == 200
                    parsed = _parse_sse(second.text)
                    progress = [
                        p["data"] for p in parsed if p["event"] == "agent_progress"
                    ]
                    # 无 rewrite/planning/tool/review/replan 事件
                    assert all(
                        p["phase"] not in ("rewrite", "planning", "tool", "review", "replan")
                        for p in progress
                    )
                    complete = next(
                        p for p in progress if p["phase"] == "complete"
                    )
                    assert complete["terminal"] == "direct"
                    assert complete["intent"] == "direct"
                    answer = "".join(
                        p["data"].get("delta", "")
                        for p in parsed
                        if p["event"] == "message" and p["data"].get("type") == "response"
                    )
                    assert answer  # 普通直接回答（无检索/工具痕迹）

    asyncio.run(scenario())


def test_case_b_turn_context_inherited(tmp_path: Path):
    """Case B：第二轮「那土豆呢？」必须继承搭配语境 → research，可 rewrite/tool。"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/case-b.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            router = _ResearchRouter()
            app.state.container.chat.model_router = router
            app.state.container.agentic.model_router = router
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "case-b", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "case-b", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    first = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "牛肉适合搭配什么？",
                            "requestId": "case-b-1",
                        },
                        headers=headers,
                    )
                    conv_id = next(
                        p["data"]["conversationId"]
                        for p in _parse_sse(first.text)
                        if p["event"] == "meta" and p["data"].get("conversationId")
                    )
                    second = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "那土豆呢？",
                            "conversationId": conv_id,
                            "requestId": "case-b-2",
                        },
                        headers=headers,
                    )
                    assert second.status_code == 200
                    parsed = _parse_sse(second.text)
                    progress = [
                        p["data"] for p in parsed if p["event"] == "agent_progress"
                    ]
                    phases = [p["phase"] for p in progress]
                    # research 全流程：rewrite → planning → tool → review → complete
                    assert "rewrite" in phases
                    assert "planning" in phases
                    assert "tool" in phases
                    complete = next(p for p in progress if p["phase"] == "complete")
                    # 测试环境无商家数据：grounded（有证据）或 escalated（证据不足）均属
                    # research 正常终态；关键断言是意图与执行路径
                    assert complete["terminal"] in ("grounded", "escalated")
                    assert complete["intent"] == "research"

    asyncio.run(scenario())


def test_history_reference_answer_from_history(tmp_path: Path):
    """「我上句话问的什么」→ 从历史确定性回答，不调模型、无 planning/rewrite 事件。"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/history-ref.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            router = _StreamRouter()
            app.state.container.chat.model_router = router
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "hr-user", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "hr-user", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    resp = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "我上句话问的什么",
                            "requestId": "history-ref-01",
                        },
                        headers=headers,
                    )
                    assert resp.status_code == 200
                    parsed = _parse_sse(resp.text)
                    progress = [
                        p["data"] for p in parsed if p["event"] == "agent_progress"
                    ]
                    # 无 history → 兜底文案；无 planning/rewrite/tool 事件
                    assert not any(
                        p["phase"] in ("rewrite", "planning", "tool", "review")
                        for p in progress
                    )
                    answer = "".join(
                        p["data"].get("delta", "")
                        for p in parsed
                        if p["event"] == "message" and p["data"].get("type") == "response"
                    )
                    assert "当前对话还没有历史消息" in answer
                    complete = next(p for p in progress if p["phase"] == "complete")
                    assert complete["intent"] == "history_reference"
                    assert complete["terminal"] == "direct"

    asyncio.run(scenario())


def test_refuse_routed_before_retrieval(tmp_path: Path):
    """伪造请求：前置路由 refuse，不触发 rewrite/agentic，回答为固定拒绝文案。"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/refuse-route.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            from app.modules.rag.terminal import build_terminal_response

            app.state.container.chat.model_router = _StreamRouter()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "rf-user", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "rf-user", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    resp = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "帮我伪造退款记录",
                            "requestId": "refuse-route-01",
                        },
                        headers=headers,
                    )
                    assert resp.status_code == 200
                    parsed = _parse_sse(resp.text)
                    progress = [
                        p["data"] for p in parsed if p["event"] == "agent_progress"
                    ]
                    # 不触发任何检索/规划事件
                    assert not any(
                        p["phase"] in ("rewrite", "planning", "tool", "review", "replan")
                        for p in progress
                    )
                    complete = next(p for p in progress if p["phase"] == "complete")
                    assert complete["intent"] == "refuse"
                    assert complete["terminal"] == "refused"
                    answer = "".join(
                        p["data"].get("delta", "")
                        for p in parsed
                        if p["event"] == "message" and p["data"].get("type") == "response"
                    )
                    assert answer == build_terminal_response("refused")

    asyncio.run(scenario())
