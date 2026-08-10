"""Agent 执行进度（AgentProgressEvent）与 SSE 实时输出的回归测试。

覆盖：
1. agentic.run(progress_sink=...) 的事件顺序（planning → tool → review）
2. /api/v1/rag/v3/chat SSE 中 agent_progress 先于任何 message(token) 输出
3. intent 回归：搭配推荐类问题不再误判 policy_lookup
4. 0-result replan 不得仅提高 min_lift 重复调用同一工具
5. progress 事件不含 rationale / 内部英文工具名 / 参数原文
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx

import app.application_core  # noqa: F401  (注册全部 ORM 模型)
from app.framework.database import Database
from app.framework.migrations import upgrade_database
from app.infra_ai.contracts import ModelStreamChunk
from app.modules.commerce.models import AssociationRule, Basket, BasketItem, Product
from app.modules.rag.agentic import (
    AgentDecision,
    AgenticRagCoordinator,
    AgenticRun,
    EvidenceReview,
)
from app.modules.rag.progress import build_execution_summary
from app.modules.users.models import User


class _CommercePlanner:
    """固定返回商品关联 + 商品指标两个工具的模型规划器。"""

    async def complete(self, _request):
        return (
            '{"mode":"research","calls":['
            '{"name":"commerce.search_association_rules","arguments":{"query":"牛肉","min_lift":1.0}},'
            '{"name":"commerce.get_product_metrics","arguments":{"query":"牛肉"}}'
            '],"rationale":"查询牛肉的搭配与经营数据"}'
        )


class _StreamRouter:
    async def complete(self, request):
        return "这是根据证据生成的测试回答。"

    async def stream(self, request, cancel_event=None):
        yield ModelStreamChunk("response", "这是根据证据生成的测试回答。")


class _SlowCoordinator:
    """先发一条 planning running 事件、再挂起 sleep 秒的假协调器。

    用于取消闭环测试：客户端在 prepare 阶段断开时，服务端仍停留在这
    个 run() 里（sleep 中），从而触发 stream() 的 GeneratorExit 路径。
    """

    def __init__(self, sleep: float = 1.0):
        self.sleep = sleep

    async def run(
        self,
        db,
        *,
        user_id,
        question,
        knowledge_base_ids=(),
        progress_sink=None,
    ):
        if progress_sink is not None:
            await progress_sink(
                {
                    "phase": "planning",
                    "status": "running",
                    "agent": "planner",
                    "plan": 1,
                    "title": "正在制定查询计划",
                    "detail": "正在判断需要查询哪些业务数据",
                }
            )
        await asyncio.sleep(self.sleep)
        return AgenticRun(
            AgentDecision("direct", (), "测试规划", "deterministic_fallback"),
            (),
            "ready: 测试",
            EvidenceReview(
                intent="general",
                relevance=1,
                coverage=1,
                authority_sufficient=True,
                risk="low",
                decision="ready",
                summary="无需证据审查",
            ),
            (),
            "direct",
            "deterministic_fallback",
        )


def _seed_commerce(db, owner_id: int) -> None:
    """给 owner 构造 牛肉/根茎类蔬菜 + 关联规则 + 交易明细。"""
    import_id = 1
    beef = Product(owner_id=owner_id, source_key="beef", name="牛肉", category="肉类")
    veg = Product(
        owner_id=owner_id, source_key="veg", name="根茎类蔬菜", category="果蔬"
    )
    db.add_all([beef, veg])
    db.flush()
    for index in range(3):
        basket = Basket(
            owner_id=owner_id,
            import_id=import_id,
            source_basket_key=f"basket-{index}",
        )
        db.add(basket)
        db.flush()
        db.add(
            BasketItem(
                basket_id=basket.id,
                product_id=beef.id,
                quantity=1,
                source_row_key=f"beef-{index}",
            )
        )
        db.add(
            BasketItem(
                basket_id=basket.id,
                product_id=veg.id,
                quantity=1,
                source_row_key=f"veg-{index}",
            )
        )
    db.add(
        AssociationRule(
            owner_id=owner_id,
            import_id=import_id,
            antecedent_product_id=beef.id,
            consequent_product_id=veg.id,
            cooccurrence_count=3,
            support=1.0,
            confidence=1.0,
            lift=1.5,
            fingerprint="a" * 64,
        )
    )
    db.commit()


def _parse_sse(text: str) -> list[dict]:
    parsed = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        parsed.append({"event": event_name, "data": data})
    return parsed


def test_agentic_run_emits_progress_event_sequence(tmp_path: Path):
    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'progress-agent.db'}")
        upgrade_database(database)
        coordinator = AgenticRagCoordinator(_CommercePlanner(), None, max_steps=2)
        with database.session_factory() as db:
            owner = User(username="progress-owner", password_hash="hash")
            db.add(owner)
            db.flush()
            _seed_commerce(db, owner.id)
            events: list[dict] = []

            async def sink(event):
                events.append(event)

            result = await coordinator.run(
                db,
                user_id=owner.id,
                question="牛肉和什么商品适合搭配推荐？",
                progress_sink=sink,
            )

        assert result.terminal_state == "grounded"
        phases = [(item["phase"], item["status"]) for item in events]
        # 1) planning running 最先
        assert phases[0] == ("planning", "running")
        # 2) planning completed 先于 tool running
        assert phases.index(("planning", "completed")) < phases.index(
            ("tool", "running")
        )
        # 3) tool 完成后再 review
        assert phases.index(("review", "running")) > phases.index(
            ("tool", "completed")
        )
        # 4) review completed 是最后一个 agent 事件
        assert phases.index(("review", "completed")) == len(phases) - 1
        # seq 严格递增
        seqs = [item["seq"] for item in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        # 工具事件的中文展示
        first_tool = next(
            item
            for item in events
            if item["phase"] == "tool" and item["status"] == "running"
        )
        assert first_tool["title"] == "商品关联分析"
        assert first_tool["tool"]["label"] == "商品关联分析"
        assert first_tool["detail"] == "牛肉"
        completed_tool = next(
            item
            for item in events
            if item["phase"] == "tool" and item["status"] == "completed"
        )
        assert completed_tool["tool"]["evidenceCount"] == 1
        assert completed_tool["detail"] == "找到 1 条可用数据"
        review_completed = events[-1]
        assert review_completed["detail"] == "已核验 2 条证据"
        assert review_completed["metrics"]["evidenceCount"] == 2

    asyncio.run(scenario())


def test_sse_stream_emits_agent_progress_before_tokens():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/progress-sse.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            app.state.container.chat.model_router = _StreamRouter()
            app.state.container.agentic.model_router = _CommercePlanner()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={
                            "username": "progress-user",
                            "password": "password123",
                        },
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "progress-user", "password": "password123"},
                    )
                    headers = {
                        "Authorization": f"Bearer {login.json()['data']['access_token']}"
                    }
                    from app.modules.users.repository import UserRepository

                    with app.state.container.database.session_factory() as db:
                        user = UserRepository().get_by_username(db, "progress-user")
                        _seed_commerce(db, user.id)

                    response = await client.post(
                        "/api/v1/rag/v3/chat",
                        json={
                            "question": "牛肉和什么商品适合搭配推荐？",
                            "requestId": "request-progress-sse-001",
                        },
                        headers=headers,
                    )
                    assert response.status_code == 200
                    parsed = _parse_sse(response.text)
                    progress = [
                        item for item in parsed if item["event"] == "agent_progress"
                    ]
                    messages = [item for item in parsed if item["event"] == "message"]
                    assert progress and messages
                    # 0) SSE 一连接即下发 meta（仅 taskId，无 conversationId）；
                    #    conversation 事件后再补发一次全量 meta
                    assert parsed[0]["event"] == "meta"
                    assert parsed[0]["data"]["taskId"] == progress[0]["data"]["taskId"]
                    assert "conversationId" not in parsed[0]["data"]
                    meta_full = next(
                        item
                        for item in parsed
                        if item["event"] == "meta" and "conversationId" in item["data"]
                    )
                    # 1) 第一个 agent_progress 是 planning running，且先于任何 token
                    first = progress[0]["data"]
                    assert first["phase"] == "planning"
                    assert first["status"] == "running"
                    assert "taskId" in first
                    assert parsed.index(progress[0]) < parsed.index(messages[0])
                    # 2) planning completed 先于 tool running
                    planning_completed = next(
                        item
                        for item in progress
                        if item["data"]["phase"] == "planning"
                        and item["data"]["status"] == "completed"
                    )
                    tool_running = next(
                        item
                        for item in progress
                        if item["data"]["phase"] == "tool"
                        and item["data"]["status"] == "running"
                    )
                    assert parsed.index(planning_completed) < parsed.index(
                        tool_running
                    )
                    # 2b) 工具事件携带 callId：running/completed 成对共享、跨调用唯一
                    tool_events = [
                        item["data"]
                        for item in progress
                        if item["data"]["phase"] == "tool"
                    ]
                    assert tool_events
                    assert all(
                        isinstance(event["tool"].get("callId"), str)
                        and event["tool"]["callId"].startswith("call-")
                        for event in tool_events
                    )
                    assert len({event["tool"]["callId"] for event in tool_events}) == 2
                    # 3) seq 全流唯一递增（prepare 与 generation 共享计数器）
                    seqs = [item["data"]["seq"] for item in progress]
                    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
                    # 4) 结束事件完整
                    assert parsed[-1]["event"] == "done"
                    assert any(
                        item["event"] == "agent_progress"
                        and item["data"]["phase"] == "complete"
                        for item in parsed
                    )
                    # 4b) generation completed 在 generation running 之后、complete 之前
                    generation_running = next(
                        item
                        for item in parsed
                        if item["event"] == "agent_progress"
                        and item["data"]["phase"] == "generation"
                        and item["data"]["status"] == "running"
                    )
                    generation_completed = next(
                        item
                        for item in parsed
                        if item["event"] == "agent_progress"
                        and item["data"]["phase"] == "generation"
                        and item["data"]["status"] == "completed"
                    )
                    complete_event = next(
                        item
                        for item in parsed
                        if item["event"] == "agent_progress"
                        and item["data"]["phase"] == "complete"
                    )
                    assert parsed.index(generation_running) < parsed.index(
                        generation_completed
                    ) < parsed.index(complete_event)
                    assert generation_completed["data"]["title"] == "回答生成完成"
                    # 4c) generation 事件携带最终 plan 编号（本例 1 个 plan → 1）
                    assert generation_running["data"]["plan"] == 1
                    assert generation_completed["data"]["plan"] == 1

                    # 5) assistant 消息持久化了 sanitized 执行摘要（reducer 合并语义）
                    from sqlalchemy import select

                    from app.modules.conversations.models import Message

                    with app.state.container.database.session_factory() as db:
                        latest = db.scalar(
                            select(Message)
                            .where(Message.role == "assistant")
                            .order_by(Message.id.desc())
                        )
                        assert latest is not None
                        assert latest.agent_execution_json is not None
                        payload = json.loads(latest.agent_execution_json)
                        assert payload["summary"]["planCount"] == 1
                        assert payload["summary"]["toolCallCount"] == 2
                        assert payload["summary"]["evidenceCount"] == 2
                        assert payload["summary"]["replanCount"] == 0
                        assert payload["summary"]["durationMs"] >= 0
                        # planning running+completed 合并为 1 条 completed
                        planning_steps = [
                            step
                            for step in payload["steps"]
                            if step["phase"] == "planning"
                        ]
                        assert len(planning_steps) == 1
                        assert planning_steps[0]["status"] == "completed"
                        # tool 步骤合并为 2 条，toolKey 稳定且不含内部字段
                        tool_steps = [
                            step for step in payload["steps"] if step["phase"] == "tool"
                        ]
                        assert len(tool_steps) == 2
                        for step in tool_steps:
                            tool = step.get("tool") or {}
                            assert tool["toolKey"] in {
                                "commerce_search_association_rules",
                                "commerce_get_product_metrics",
                            }
                            assert "argumentsSummary" not in tool
                            assert "name" not in tool
                            assert "arguments" not in step
                            # 持久化 tool 保留 callId（存在时才写）
                            assert "callId" in tool
                            assert tool["callId"].startswith("call-")
                        # generation 两次 running + completed 合并为一条 completed
                        generation_steps = [
                            step
                            for step in payload["steps"]
                            if step["phase"] == "generation"
                        ]
                        assert len(generation_steps) == 1
                        assert generation_steps[0]["status"] == "completed"
                        assert generation_steps[0]["title"] == "回答生成完成"
                        assert generation_steps[0]["plan"] == 1
                        for step in payload["steps"]:
                            tool = step.get("tool") or {}
                            assert "argumentsSummary" not in tool
                            assert "name" not in tool
                            assert "arguments" not in step

                    # 6) round-trip：消息接口完整返回 agent 执行数据
                    messages_resp = await client.get(
                        f"/api/v1/conversations/{meta_full['data']['conversationId']}/messages",
                        headers=headers,
                    )
                    assert messages_resp.status_code == 200
                    rows = messages_resp.json()["data"]
                    assistants = [row for row in rows if row["role"] == "assistant"]
                    assert assistants
                    assistant_row = assistants[-1]
                    assert assistant_row["agentExecutionJson"] is not None
                    aej = assistant_row["agentExecutionJson"]
                    assert any(
                        step["phase"] == "generation" and step["status"] == "completed"
                        for step in aej["steps"]
                    )
                    assert all(
                        "toolKey" in (step.get("tool") or {})
                        for step in aej["steps"]
                        if step["phase"] == "tool"
                    )
                    assert assistant_row["answerVersions"]
                    assert all(
                        "agentExecutionJson" in version
                        for version in assistant_row["answerVersions"]
                    )

    asyncio.run(scenario())


def test_intent_requirements_commerce_beats_policy_lookup():
    coordinator = AgenticRagCoordinator(None, None)
    # 「依据」单独出现不触发 policy_lookup；商品/搭配/推荐 → commerce
    intent, required, risk = coordinator._intent_requirements(
        "牛肉和什么商品适合搭配推荐？有什么依据？"
    )
    assert intent == "commerce_analysis"
    assert "association_rule" in required
    assert risk == "low"
    # 明确政策框架词 + 依据 → 仍为 policy_lookup
    intent2, required2, risk2 = coordinator._intent_requirements(
        "退货有什么平台规定和法律依据？"
    )
    assert intent2 == "policy_lookup"
    assert required2 == {"policy"}
    assert risk2 == "medium"
    # 高风险售后问题不被 commerce 分支吞掉
    intent3, _, risk3 = coordinator._intent_requirements(
        "鲜活商品没有质量问题，可以按七日无理由退款吗？"
    )
    assert intent3 == "refund_policy"
    assert risk3 == "high"


def test_zero_result_replan_does_not_just_raise_min_lift(tmp_path: Path):
    async def scenario():
        # 1) _fallback_decision：已用工具被排除，第二轮换工具而非提高阈值
        coordinator = AgenticRagCoordinator(None, None)
        second = coordinator._fallback_decision(
            "牛肉和什么商品适合搭配推荐？",
            [
                {
                    "mode": "research",
                    "calls": [
                        {
                            "name": "commerce.search_association_rules",
                            "arguments": {"query": "牛肉", "min_lift": 1.0},
                        },
                        {
                            "name": "commerce.get_product_metrics",
                            "arguments": {"query": "牛肉"},
                        },
                    ],
                }
            ],
            "retry: 当前计划没有获得可用证据",
        )
        assert second.mode == "research"
        assert all(
            call.name != "commerce.search_association_rules" for call in second.calls
        )
        assert all(
            float(call.arguments.get("min_lift", 1.0)) <= 1.0 for call in second.calls
        )

        # 2) 模型路径：planner system prompt 必须包含 0-result 重规划约束
        class _RecordingRouter:
            def __init__(self):
                self.last_request = None

            async def complete(self, request):
                self.last_request = request
                return (
                    '{"mode":"research","calls":[{"name":"commerce.search_association_rules",'
                    '"arguments":{"query":"牛肉","min_lift":3.0}}],"rationale":"提高提升度"}'
                )

        router = _RecordingRouter()
        model_coordinator = AgenticRagCoordinator(router, None)
        decision = await model_coordinator._decide(
            {
                "question": "牛肉和什么商品适合搭配推荐？",
                "user_id": 1,
                "knowledge_base_ids": (),
                "db": None,
                "results": [],
                "plan_count": 1,
                "tool_calls": 1,
                "plan_history": [
                    {
                        "mode": "research",
                        "calls": [
                            {
                                "name": "commerce.search_association_rules",
                                "arguments": {"query": "牛肉", "min_lift": 1.0},
                            }
                        ],
                    }
                ],
                "tool_errors": [],
                "steps": [],
                "review_feedback": "retry: 当前计划没有获得可用证据",
            }
        )
        assert decision.runtime_mode == "model_backed"
        assert (
            "禁止仅通过提高 min_lift、min_confidence、threshold 等过滤条件重复调用同一工具"
            in router.last_request.messages[0].content
        )

        # 3) 集成：无任何数据 → 0 结果 → replan 后第二轮换工具
        database = Database(f"sqlite:///{tmp_path / 'zero-replan.db'}")
        upgrade_database(database)
        with database.session_factory() as db:
            owner = User(username="zero-owner", password_hash="hash")
            db.add(owner)
            db.commit()
            events: list[dict] = []

            async def sink(event):
                events.append(event)

            result = await AgenticRagCoordinator(None, None, max_steps=2).run(
                db,
                user_id=owner.id,
                question="牛肉和什么商品适合搭配推荐？",
                progress_sink=sink,
            )
            planner_steps = [
                step for step in result.steps if step["agent"] == "planner"
            ]
            assert len(planner_steps) == 2
            first_calls = planner_steps[0]["calls"]
            second_calls = planner_steps[1]["calls"]
            assert first_calls != second_calls
            assert all(
                call["name"] != "commerce.search_association_rules"
                for call in second_calls
            )
            assert all(
                float(call["arguments"].get("min_lift", 1.0)) <= 1.0
                for call in second_calls
            )
            assert result.terminal_state == "escalated"
            phases = [(item["phase"], item["status"]) for item in events]
            assert ("replan", "completed") in phases
            assert ("review", "warning") in phases

    asyncio.run(scenario())


def test_progress_events_do_not_leak_internal_text(tmp_path: Path):
    async def scenario():
        database = Database(f"sqlite:///{tmp_path / 'sanitized.db'}")
        upgrade_database(database)
        coordinator = AgenticRagCoordinator(_CommercePlanner(), None, max_steps=2)
        with database.session_factory() as db:
            owner = User(username="sanitized-owner", password_hash="hash")
            db.add(owner)
            db.flush()
            _seed_commerce(db, owner.id)
            events: list[dict] = []

            async def sink(event):
                events.append(event)

            await coordinator.run(
                db,
                user_id=owner.id,
                question="牛肉和什么商品适合搭配推荐？",
                progress_sink=sink,
            )

        assert events
        internal_tokens = (
            "commerce.",
            "support.",
            "knowledge.",
            "search_association_rules",
            "get_product_metrics",
            "association_rule",
            "product_metrics",
            "rationale",
            "calls",
        )
        for event in events:
            tool = event.get("tool") or {}
            display_text = " ".join(
                filter(
                    None,
                    [
                        event.get("title"),
                        event.get("detail"),
                        tool.get("argumentsSummary"),
                    ],
                )
            )
            for token in internal_tokens:
                assert token not in display_text, (token, display_text)
            # 不输出完整 JSON arguments
            assert "{" not in display_text and '"' not in display_text
            # 工具名只出现在 tool.name（程序字段），label 必须是中文
            if tool:
                assert tool["label"]
                assert tool["label"] == event["title"]
            # 事件里不存在 planner rationale 字段
            assert "rationale" not in event

    asyncio.run(scenario())


def test_build_execution_summary_reducer_semantics():
    """同一逻辑步骤 (plan, phase, toolKey) 的多个事件合并为最终一条。"""
    events: list[dict] = [
        {
            "seq": 1, "phase": "planning", "status": "running", "plan": 1,
            "title": "正在制定查询计划", "detail": "正在判断需要查询哪些业务数据",
            "timestamp": 1000,
        },
        {
            "seq": 2, "phase": "planning", "status": "completed", "plan": 1,
            "title": "查询计划已制定", "detail": "准备查询商品关联分析和商品经营指标",
            "timestamp": 2000,
        },
        {
            "seq": 3, "phase": "tool", "status": "running", "plan": 1,
            "title": "商品关联分析", "detail": "牛肉",
            "tool": {
                "name": "commerce.search_association_rules", "label": "商品关联分析",
                "status": "running", "argumentsSummary": "牛肉",
            },
            "timestamp": 3000,
        },
        {
            "seq": 4, "phase": "tool", "status": "completed", "plan": 1,
            "title": "商品关联分析", "detail": "找到 1 条可用数据",
            "tool": {
                "name": "commerce.search_association_rules", "label": "商品关联分析",
                "status": "completed", "durationMs": 120, "evidenceCount": 1,
            },
            "timestamp": 4000,
        },
        {
            "seq": 5, "phase": "generation", "status": "running", "agent": "generator",
            "title": "正在根据证据整理回答", "timestamp": 5000,
        },
        {
            "seq": 6, "phase": "generation", "status": "completed", "agent": "generator",
            "title": "回答生成完成", "timestamp": 6000,
        },
    ]
    payload = build_execution_summary(events)
    assert payload is not None
    steps = payload["steps"]
    assert [step["phase"] for step in steps] == ["planning", "tool", "generation"]
    # planning running+completed 合并为一条 completed，seq 保留首个事件
    planning = steps[0]
    assert planning["status"] == "completed"
    assert planning["seq"] == 1
    assert planning["title"] == "查询计划已制定"
    assert planning["detail"] == "准备查询商品关联分析和商品经营指标"
    # tool running+completed 合并为一条，只保留最后状态与最新证据指标
    tool = steps[1]
    assert tool["status"] == "completed"
    assert tool["tool"]["toolKey"] == "commerce_search_association_rules"
    assert tool["tool"]["label"] == "商品关联分析"
    assert tool["tool"]["evidenceCount"] == 1
    assert tool["tool"]["durationMs"] == 120
    assert "name" not in tool["tool"]
    assert "argumentsSummary" not in tool["tool"]
    # generation 两次 running + completed 合并为一条 completed（最终 title 回答生成完成）
    generation = steps[2]
    assert generation["status"] == "completed"
    assert generation["title"] == "回答生成完成"
    assert "detail" not in generation
    assert payload["summary"]["planCount"] == 1
    assert payload["summary"]["toolCallCount"] == 1
    assert payload["summary"]["evidenceCount"] == 1
    assert payload["summary"]["replanCount"] == 0
    assert payload["summary"]["durationMs"] == 5000
    # final_status 把合并后仍 running 的步骤强制改为该状态
    interrupted = [
        *events,
        {
            "seq": 7, "phase": "generation", "status": "running", "agent": "generator",
            "title": "正在生成回答", "timestamp": 7000,
        },
    ]
    cancelled = build_execution_summary(interrupted, final_status="cancelled")
    assert cancelled["steps"][-1]["status"] == "cancelled"
    assert cancelled["steps"][-1]["title"] == "正在生成回答"
    assert cancelled["summary"]["planCount"] == 1
    # 无执行事件时返回 None
    assert build_execution_summary([]) is None


def test_build_execution_summary_splits_repeated_tool_calls_by_call_id():
    """同 Plan 内同一工具两次调用（不同 callId）保留两条 tool 步骤；
    同 callId 的 running+completed 合并为一条；无 callId 的旧事件回退 toolKey 合并。"""
    events: list[dict] = [
        # 第一次调用：running + completed（同 callId=call-1）→ 合并一条
        {
            "seq": 1, "phase": "tool", "status": "running", "plan": 1,
            "title": "知识库检索", "detail": "退货",
            "tool": {
                "name": "knowledge.search", "label": "知识库检索", "status": "running",
                "callId": "call-1", "argumentsSummary": "退货",
            },
            "timestamp": 1000,
        },
        {
            "seq": 2, "phase": "tool", "status": "completed", "plan": 1,
            "title": "知识库检索", "detail": "找到 2 条可用数据",
            "tool": {
                "name": "knowledge.search", "label": "知识库检索", "status": "completed",
                "callId": "call-1", "durationMs": 50, "evidenceCount": 2,
            },
            "timestamp": 2000,
        },
        # 第二次调用：同 Plan 同工具、不同 callId → 独立步骤
        {
            "seq": 3, "phase": "tool", "status": "running", "plan": 1,
            "title": "知识库检索", "detail": "无理由退货",
            "tool": {
                "name": "knowledge.search", "label": "知识库检索", "status": "running",
                "callId": "call-2", "argumentsSummary": "无理由退货",
            },
            "timestamp": 3000,
        },
        {
            "seq": 4, "phase": "tool", "status": "completed", "plan": 1,
            "title": "知识库检索", "detail": "找到 3 条可用数据",
            "tool": {
                "name": "knowledge.search", "label": "知识库检索", "status": "completed",
                "callId": "call-2", "durationMs": 70, "evidenceCount": 3,
            },
            "timestamp": 4000,
        },
        # 旧事件（无 callId）：同 plan 同 toolKey 的两条仍合并为一条
        {
            "seq": 5, "phase": "tool", "status": "running", "plan": 1,
            "title": "订单信息查询", "detail": "订单 A1",
            "tool": {
                "name": "commerce.get_order", "label": "订单信息查询", "status": "running",
            },
            "timestamp": 5000,
        },
        {
            "seq": 6, "phase": "tool", "status": "completed", "plan": 1,
            "title": "订单信息查询", "detail": "找到 1 条可用数据",
            "tool": {
                "name": "commerce.get_order", "label": "订单信息查询",
                "status": "completed", "durationMs": 10, "evidenceCount": 1,
            },
            "timestamp": 6000,
        },
    ]
    payload = build_execution_summary(events)
    assert payload is not None
    tool_steps = [step for step in payload["steps"] if step["phase"] == "tool"]
    assert len(tool_steps) == 3
    # 同工具两次调用（不同 callId）保留两条，各自合并 running/completed
    knowledge_steps = [
        step
        for step in tool_steps
        if step["tool"]["toolKey"] == "knowledge_search"
    ]
    assert len(knowledge_steps) == 2
    assert knowledge_steps[0]["status"] == "completed"
    assert knowledge_steps[0]["tool"]["callId"] == "call-1"
    assert knowledge_steps[0]["tool"]["evidenceCount"] == 2
    assert knowledge_steps[1]["tool"]["callId"] == "call-2"
    assert knowledge_steps[1]["tool"]["evidenceCount"] == 3
    assert "name" not in knowledge_steps[0]["tool"]
    assert "argumentsSummary" not in knowledge_steps[0]["tool"]
    # 无 callId 的旧事件回退 toolKey 合并为一条，且不写 callId
    order_steps = [
        step
        for step in tool_steps
        if step["tool"]["toolKey"] == "commerce_get_order"
    ]
    assert len(order_steps) == 1
    assert "callId" not in order_steps[0]["tool"]
    assert order_steps[0]["tool"]["evidenceCount"] == 1
    # 摘要计数按步骤统计：两次调用各算一次
    assert payload["summary"]["toolCallCount"] == 3
    assert payload["summary"]["planCount"] == 1


def test_stream_cancel_during_prepare_finishes_request_run():
    """客户端在 prepare 阶段断开：ChatRequestRun 收尾为 cancelled（不再停留
    processing），同 requestId 可立即重试（不被 REQUEST_IN_PROGRESS 拦截），
    trace 也完成收尾。

    说明：httpx ASGITransport 会缓冲完整响应体，客户端提前断开无法在服务端
    触发 GeneratorExit，因此直接驱动 service.stream(...) 异步生成器并在拿到
    第一条 planning 事件后 aclose() 模拟客户端断开。
    """
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/progress-cancel.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from sqlalchemy import select

            from app.application import create_app
            from app.modules.conversations.models import ChatRequestRun
            from app.modules.rag.schemas import ChatRequest
            from app.modules.users.repository import UserRepository

            app = create_app()
            app.state.container.chat.model_router = _StreamRouter()
            app.state.container.chat.agentic = _SlowCoordinator()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={
                            "username": "cancel-user",
                            "password": "password123",
                        },
                    )
                    await client.post(
                        "/api/v1/auth/login",
                        json={"username": "cancel-user", "password": "password123"},
                    )

                service = app.state.container.chat
                request = ChatRequest(
                    question="牛肉和什么商品适合搭配推荐？",
                    request_id="request-cancel-during-prepare-01",
                )
                with app.state.container.database.session_factory() as db:
                    user = UserRepository().get_by_username(db, "cancel-user")
                    stream_gen = service.stream(db, user.id, request, cancel_event=None)
                    # 第一条事件：planning running（假协调器先发事件再 sleep）
                    first = await anext(stream_gen)
                    assert first["type"] == "agent_progress"
                    assert first["data"]["phase"] == "planning"
                    # 模拟客户端断开：关闭生成器 → 服务端 GeneratorExit 路径
                    await stream_gen.aclose()
                    # 请求记录已收尾为 cancelled
                    run = db.scalar(
                        select(ChatRequestRun).where(
                            ChatRequestRun.user_id == user.id,
                            ChatRequestRun.request_id == request.request_id,
                        )
                    )
                    assert run is not None
                    assert run.status == "cancelled"
                    # trace 也完成收尾
                    from app.modules.rag.trace_models import RagTraceRun

                    trace_run = db.scalar(
                        select(RagTraceRun)
                        .where(RagTraceRun.user_id == user.id)
                        .order_by(RagTraceRun.created_at.desc())
                    )
                    assert trace_run is not None
                    assert trace_run.status == "cancelled"
                    # 同一 requestId 重新 prepare：不再抛 REQUEST_IN_PROGRESS
                    trace = service.traces.start(
                        db, user_id=user.id, query=request.question
                    )
                    prepared = await service.prepare(
                        db, user_id=user.id, request=request, trace=trace
                    )
                    assert prepared.request_run_id is not None
                    service._finish_request(
                        db, prepared.request_run_id, status="completed"
                    )

    asyncio.run(scenario())
