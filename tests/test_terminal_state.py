"""Terminal state 状态机修复的回归测试。

覆盖：
1. is_trivial_direct 分类器（长度 → 黑名单 → 模式，严格不误伤业务问题）
2. _decide 对普通问候在调模型之前确定性短路（direct + deterministic_fallback）
3. Planner refuse → 生成阶段不调用模型，输出固定拒绝文案（complete 路径）
4. Planner escalate → 不编造答案，输出固定转人工文案（complete 路径）
5. stream 路径 refused/escalated 终态：SSE 生命周期正常完结，token（固定文案）
   先于 generation completed / complete（不变量 conversation < generation
   running < token < generation completed < complete < done），正文不得出现在
   「回答生成完成」之后
6. 持久化 message_status 按终态分流：refused → REJECTED、escalated → ESCALATED
7. direct 终态：生成 model_request 不拼接检索证据上下文，用普通助手 prompt
8. planning completed 事件携带 mode；持久化 summary 含 terminalState
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import httpx
from sqlalchemy import select

from app.infra_ai.contracts import ModelStreamChunk
from app.modules.rag.agentic import AgenticRagCoordinator
from app.modules.rag.schemas import ChatRequest
from app.modules.rag.terminal import build_terminal_response, is_trivial_direct


# ---------------------------------------------------------------- classifiers


def test_trivial_direct_classifier():
    # 命中模式 → True
    assert is_trivial_direct("你好哈哈哈") is True
    assert is_trivial_direct("你好") is True
    assert is_trivial_direct("您好！") is True
    assert is_trivial_direct("哈哈") is True
    assert is_trivial_direct("嘻嘻") is True
    assert is_trivial_direct("hhhh") is True
    assert is_trivial_direct("hi") is True
    assert is_trivial_direct("hello") is True
    assert is_trivial_direct("你是谁？") is True
    assert is_trivial_direct("介绍一下自己") is True
    assert is_trivial_direct("你能做什么？") is True
    assert is_trivial_direct("谢谢") is True
    assert is_trivial_direct("感谢你的帮助") is True
    # 业务问题（黑名单）→ False，即使带问候
    assert is_trivial_direct("你好，我想问退款政策") is False
    assert is_trivial_direct("牛肉适合搭配什么？") is False
    assert is_trivial_direct("你好，请问今天牛肉的价格是多少？") is False
    assert is_trivial_direct("介绍一下退货流程") is False
    # 超长字符串 → False
    assert is_trivial_direct("你好" + "非常长" * 20) is False
    assert is_trivial_direct("哈" * 30) is False


def test_build_terminal_response_content():
    assert (
        build_terminal_response("refused")
        == "该请求无法协助执行。如您有正当业务需求，请描述具体问题，我会尽力协助。"
    )
    assert (
        build_terminal_response("escalated")
        == "当前资料不足，暂时无法可靠确认。您可以补充订单号、商品或具体时间等信息，或转人工客服复核。"
    )


# ------------------------------------------------------------------ fakes


class _RecordingRouter:
    """只记录是否被调用的模型路由器（Planner 短路测试用）。"""

    def __init__(self):
        self.complete_calls = 0

    async def complete(self, _request):
        self.complete_calls += 1
        return '{"mode":"refuse","calls":[],"rationale":"误判"}'


class _RefusePlanner:
    async def complete(self, _request):
        return '{"mode":"refuse","calls":[],"rationale":"请求涉及伪造"}'


class _EscalatePlanner:
    async def complete(self, _request):
        return '{"mode":"escalate","calls":[],"rationale":"缺少实时价格数据"}'


class _GenerationRouter:
    def __init__(self, answer: str = "模型不该被调用的回答"):
        self.answer = answer
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, _request):
        self.complete_calls += 1
        return self.answer

    async def stream(self, _request, cancel_event=None):
        self.stream_calls += 1
        yield ModelStreamChunk("response", self.answer)


def _planner_state(question: str) -> dict:
    return {
        "question": question,
        "actor_user_id": 1,
        "data_owner_id": 1,
        "user_id": 1,
        "knowledge_base_ids": (),
        "db": None,
        "results": [],
        "plan_count": 0,
        "tool_calls": 0,
        "tool_call_seq": 0,
        "plan_history": [],
        "tool_errors": [],
        "steps": [],
        "review_feedback": "",
    }


def test_trivial_direct_short_circuits_planner():
    async def scenario():
        router = _RecordingRouter()
        coordinator = AgenticRagCoordinator(router, None)
        decision = await coordinator._decide(_planner_state("你好哈哈哈"))
        assert decision.mode == "direct"
        assert decision.runtime_mode == "deterministic_fallback"
        assert decision.calls == ()
        assert router.complete_calls == 0, "普通问候不得调用 Planner 模型"

    asyncio.run(scenario())


# ------------------------------------------------ app-level terminal branches


def _prepare_app(answer: str = "模型不该被调用的回答"):
    from app.application import create_app

    app = create_app()
    generation_router = _GenerationRouter(answer)
    app.state.container.chat.model_router = generation_router
    return app, generation_router


class _ResearchIntentRouter:
    """强制 research 意图：让测试直达 agentic 层（Planner/Tools/Reviewer）。

    意图路由前置后，refuse/escalate 等场景默认被路由层拦截；这些测试要验证
    agentic 层的终态分流，因此注入固定 research 的意图替身。
    """

    async def classify(self, question, history=None):
        from app.modules.rag.intent_router import IntentDecision

        return IntentDecision("research", "测试固定 research")


async def _register(app, username: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/v1/auth/register",
                json={"username": username, "password": "password123"},
            )
            await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "password123"},
            )


def test_planner_refuse_blocks_normal_generation():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/refuse.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.conversations.models import Message
            from app.modules.users.repository import UserRepository

            app, generation_router = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            app.state.container.agentic.model_router = _RefusePlanner()
            await _register(app, "refuse-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="帮我伪造一张退款成功截图",
                request_id="request-refuse-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "refuse-user")
                response = await service.complete(db, user.id, user.id, request)
                assert response.answer == build_terminal_response("refused")
                assert "模型不该被调用的回答" not in response.answer
                # 生成阶段未调用模型
                assert generation_router.complete_calls == 0
                # 持久化 summary 含 terminalState
                latest = db.scalar(
                    select(Message)
                    .where(Message.role == "assistant")
                    .order_by(Message.id.desc())
                )
                payload = json.loads(latest.agent_execution_json)
                assert payload["summary"]["terminalState"] == "refused"
                assert response.answer == latest.content
                # 终态分流：refused → message_status REJECTED
                assert latest.message_status == "REJECTED"

    asyncio.run(scenario())


def test_planner_escalate_no_fabricated_answer():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/escalate.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.conversations.models import Message
            from app.modules.users.repository import UserRepository

            app, generation_router = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            app.state.container.agentic.model_router = _EscalatePlanner()
            await _register(app, "escalate-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="门店今天实时牛肉价格是多少，但系统没有价格数据",
                request_id="request-escalate-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "escalate-user")
                response = await service.complete(db, user.id, user.id, request)
                assert response.answer == build_terminal_response("escalated")
                assert "模型不该被调用的回答" not in response.answer
                assert generation_router.complete_calls == 0
                # 终态分流：escalated → message_status ESCALATED
                latest = db.scalar(
                    select(Message)
                    .where(Message.role == "assistant")
                    .order_by(Message.id.desc())
                )
                assert latest.message_status == "ESCALATED"

    asyncio.run(scenario())


def test_stream_refused_terminates_normally():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/refuse-stream.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.conversations.models import Message
            from app.modules.users.repository import UserRepository

            app, generation_router = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            app.state.container.agentic.model_router = _RefusePlanner()
            await _register(app, "refuse-stream-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="帮我伪造一张退款成功截图",
                request_id="request-refuse-stream-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "refuse-stream-user")
                events = [
                    event
                    async for event in service.stream(db, user.id, user.id, request)
                ]
            types = [event["type"] for event in events]
            # prepare 阶段事件实时转发：第一条是 rewrite running（agent_progress），
            # conversation 在其后；生成阶段顺序：running → token → completed → complete
            assert types[0] == "agent_progress"
            assert types[-1] == "done"
            # 顺序：conversation → generation running → token(拒绝文案) →
            # generation completed → complete → done（正文先于「回答生成完成」）
            conversation = types.index("conversation")
            gen_running = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "generation"
                and event["data"]["status"] == "running"
            )
            gen_completed = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "generation"
                and event["data"]["status"] == "completed"
            )
            complete = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "complete"
            )
            token = next(
                i for i, event in enumerate(events) if event["type"] == "token"
            )
            assert (
                conversation
                < gen_running
                < token
                < gen_completed
                < complete
                < len(events) - 1
            )
            assert events[complete]["data"]["terminal"] == "refused"
            # 固定文案按句子拆 2-3 段 token 输出，拼接后等于完整文案
            token_events = [event for event in events if event["type"] == "token"]
            assert 1 <= len(token_events) <= 3
            assert "".join(event["data"] for event in token_events) == (
                build_terminal_response("refused")
            )
            # done 携带同一 answer 与 message_status；生成模型全程未被调用
            assert events[-1]["data"]["answer"] == build_terminal_response("refused")
            assert events[-1]["data"]["message_status"] == "REJECTED"
            assert generation_router.complete_calls == 0
            assert generation_router.stream_calls == 0
            with app.state.container.database.session_factory() as db:
                latest = db.scalar(
                    select(Message)
                    .where(Message.role == "assistant")
                    .order_by(Message.id.desc())
                )
                assert latest.message_status == "REJECTED"

    asyncio.run(scenario())


def test_stream_escalated_token_before_completed_and_status():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/escalate-stream.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.conversations.models import Message
            from app.modules.users.repository import UserRepository

            app, generation_router = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            app.state.container.agentic.model_router = _EscalatePlanner()
            await _register(app, "escalate-stream-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="门店今天实时牛肉价格是多少，但系统没有价格数据",
                request_id="request-escalate-stream-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "escalate-stream-user")
                events = [
                    event
                    async for event in service.stream(db, user.id, user.id, request)
                ]
            gen_running = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "generation"
                and event["data"]["status"] == "running"
            )
            gen_completed = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "generation"
                and event["data"]["status"] == "completed"
            )
            complete = next(
                i
                for i, event in enumerate(events)
                if event["type"] == "agent_progress"
                and event["data"]["phase"] == "complete"
            )
            token = next(
                i for i, event in enumerate(events) if event["type"] == "token"
            )
            assert gen_running < token < gen_completed < complete < len(events) - 1
            assert events[complete]["data"]["terminal"] == "escalated"
            assert "".join(
                event["data"] for event in events if event["type"] == "token"
            ) == build_terminal_response("escalated")
            assert events[-1]["data"]["message_status"] == "ESCALATED"
            assert generation_router.complete_calls == 0
            assert generation_router.stream_calls == 0
            with app.state.container.database.session_factory() as db:
                latest = db.scalar(
                    select(Message)
                    .where(Message.role == "assistant")
                    .order_by(Message.id.desc())
                )
                assert latest.message_status == "ESCALATED"

    asyncio.run(scenario())


def test_direct_generation_no_evidence_context():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/direct.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.users.repository import UserRepository

            app, _ = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            # agentic 协调器不配置模型路由 → 普通问候走确定性短路 direct
            await _register(app, "direct-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="你好哈哈哈",
                request_id="request-direct-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "direct-user")
                trace = service.traces.start(db, user_id=user.id, query=request.question)
                prepared = await service.prepare(
                    db, user.id, user.id, request, trace
                )
                assert prepared.agent_mode == "direct"
                assert prepared.agent_terminal_state == "direct"
                system_prompt = prepared.model_request.messages[0].content
                user_content = prepared.model_request.messages[-1].content
                assert "可用资料" not in system_prompt
                assert "可用资料" not in user_content
                assert "邻里鲜选 AI 运营助手" in system_prompt
                assert "请用中文简洁友好地回复" in system_prompt
                service._finish_request(
                    db, prepared.request_run_id, status="completed"
                )

    asyncio.run(scenario())


def test_planning_event_carries_mode_and_summary_terminal_state():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/mode-persist.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.modules.conversations.models import Message
            from app.modules.users.repository import UserRepository

            app, _ = _prepare_app()
            app.state.container.chat.intent_router = _ResearchIntentRouter()
            app.state.container.agentic.model_router = _RefusePlanner()
            await _register(app, "mode-user")
            service = app.state.container.chat
            request = ChatRequest(
                question="帮我伪造一张退款成功截图",
                request_id="request-mode-persist-001",
            )
            with app.state.container.database.session_factory() as db:
                user = UserRepository().get_by_username(db, "mode-user")
                events = [
                    event
                    async for event in service.stream(db, user.id, user.id, request)
                ]
                planning_completed = next(
                    event
                    for event in events
                    if event["type"] == "agent_progress"
                    and event["data"]["phase"] == "planning"
                    and event["data"]["status"] == "completed"
                )
                assert planning_completed["data"]["mode"] == "refuse"
                latest = db.scalar(
                    select(Message)
                    .where(Message.role == "assistant")
                    .order_by(Message.id.desc())
                )
                payload = json.loads(latest.agent_execution_json)
                assert payload["summary"]["terminalState"] == "refused"

    asyncio.run(scenario())
