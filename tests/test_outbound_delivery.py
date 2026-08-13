from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
from sqlalchemy import func, select

from app.framework.config import Settings
from app.modules.orders.models import OutboundMessage
from app.modules.support.models import ReplySuggestion, SupportCase, SupportMessage
from app.modules.support.outbound import WebhookChannel


def test_demo_outbound_requires_human_confirmation_and_is_idempotent(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'outbound.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "outbound-owner", "password": "password123"},
                )
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "outbound-owner", "password": "password123"},
                )
                headers = {
                    "Authorization": f"Bearer {login.json()['data']['access_token']}"
                }
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(
                        owner_id=1,
                        case_key="outbound-case-1",
                        customer_name="赵女士",
                        subject="配送延误",
                        status="pending",
                        priority="high",
                    )
                    db.add(case)
                    db.commit()
                    case_id = case.id

                payload = {
                    "content": "已核实订单状态，我们会继续跟进配送。",
                    "expectedVersion": 1,
                    "idempotencyKey": "confirm-outbound-case-1-v1",
                }
                first = await client.post(
                    f"/api/v1/support/cases/{case_id}/outbound",
                    headers=headers,
                    json=payload,
                )
                replay = await client.post(
                    f"/api/v1/support/cases/{case_id}/outbound",
                    headers=headers,
                    json=payload,
                )

                assert first.status_code == 200
                assert replay.status_code == 200
                assert replay.json()["data"] == first.json()["data"]
                result = first.json()["data"]
                assert result["channel"] == "demo"
                assert result["status"] == "sent"
                assert result["isDemo"] is True
                assert result["deliveryClaim"] == "simulated"
                with app.state.container.database.session_factory() as db:
                    assert db.scalar(select(func.count(OutboundMessage.id))) == 1
                    assert db.scalar(select(func.count(SupportMessage.id))) == 1
                    message = db.scalar(select(SupportMessage))
                    assert message.sent_to_customer is True

    asyncio.run(scenario())


def test_outbound_rejects_stale_version_and_cross_owner_case(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'outbound-guards.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                for username in ("outbound-a", "outbound-b"):
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": username, "password": "password123"},
                    )
                first_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "outbound-a", "password": "password123"},
                )
                second_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "outbound-b", "password": "password123"},
                )
                first_headers = {
                    "Authorization": f"Bearer {first_login.json()['data']['access_token']}"
                }
                second_headers = {
                    "Authorization": f"Bearer {second_login.json()['data']['access_token']}"
                }
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(
                        owner_id=1,
                        case_key="guard-case-1",
                        customer_name="钱女士",
                        subject="退款进度",
                        status="pending",
                        priority="normal",
                        version=2,
                    )
                    db.add(case)
                    db.commit()
                    case_id = case.id
                payload = {
                    "content": "正在核实。",
                    "expectedVersion": 1,
                    "idempotencyKey": "guard-attempt-1",
                }

                stale = await client.post(
                    f"/api/v1/support/cases/{case_id}/outbound",
                    headers=first_headers,
                    json=payload,
                )
                hidden = await client.post(
                    f"/api/v1/support/cases/{case_id}/outbound",
                    headers=second_headers,
                    json={**payload, "expectedVersion": 2},
                )

                assert stale.status_code == 409
                assert stale.json()["error"]["code"] == "CASE_VERSION_CONFLICT"
                assert hidden.status_code == 404
                assert hidden.json()["error"]["code"] == "SUPPORT_CASE_NOT_FOUND"

    asyncio.run(scenario())


def test_webhook_channel_signs_bounded_payload_and_maps_failures_without_retry():
    calls = []
    secret = "test-webhook-secret"

    def success_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        expected = hmac.new(secret.encode(), request.content, hashlib.sha256).hexdigest()
        assert request.headers["x-ragent-signature"] == f"sha256={expected}"
        assert json.loads(request.content) == {
            "content": "确认回复",
            "idempotencyKey": "webhook-success-1",
        }
        return httpx.Response(
            202,
            json={"externalId": "platform-msg-001", "status": "sent"},
        )

    success_client = httpx.Client(transport=httpx.MockTransport(success_handler))
    success = WebhookChannel(
        "https://merchant.example/webhook",
        secret,
        client=success_client,
        timeout_seconds=1,
    ).send(content="确认回复", idempotency_key="webhook-success-1")

    assert success.status == "sent"
    assert success.external_id == "platform-msg-001"
    assert len(calls) == 1

    def rejection_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="secret internal upstream body")

    rejection = WebhookChannel(
        "https://merchant.example/webhook",
        secret,
        client=httpx.Client(transport=httpx.MockTransport(rejection_handler)),
    ).send(content="确认回复", idempotency_key="webhook-reject-1")
    assert rejection.status == "failed"
    assert rejection.failure_reason == "WEBHOOK_HTTP_503"
    assert secret not in rejection.failure_reason

    timeout_calls = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("private timeout detail", request=request)

    timeout = WebhookChannel(
        "https://merchant.example/webhook",
        secret,
        client=httpx.Client(transport=httpx.MockTransport(timeout_handler)),
    ).send(content="确认回复", idempotency_key="webhook-timeout-1")
    assert timeout.status == "failed"
    assert timeout.failure_reason == "WEBHOOK_TIMEOUT"
    assert timeout_calls == 1


def test_legacy_manual_reply_creates_auditable_demo_outbound_projection(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'legacy-outbound.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "legacy-outbound", "password": "password123"},
                )
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "legacy-outbound", "password": "password123"},
                )
                headers = {
                    "Authorization": f"Bearer {login.json()['data']['access_token']}"
                }
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(
                        owner_id=1,
                        case_key="legacy-outbound-case",
                        customer_name="孙女士",
                        subject="人工回复",
                        status="pending",
                        priority="normal",
                    )
                    db.add(case)
                    db.commit()
                    case_id = case.id

                reply = await client.post(
                    f"/api/v1/support/cases/{case_id}/replies",
                    headers=headers,
                    json={"content": "人工已确认这条回复。"},
                )
                workspace = await client.get(
                    f"/api/v1/support/cases/{case_id}/workspace", headers=headers
                )

                assert reply.status_code == 200
                outbound = workspace.json()["data"]["outboundMessages"]
                assert len(outbound) == 1
                assert outbound[0]["channel"] == "demo"
                assert outbound[0]["isDemo"] is True

    asyncio.run(scenario())


def test_accepted_suggestion_creates_one_auditable_outbound(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'accepted-outbound.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "accepted-outbound", "password": "password123"},
                )
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "accepted-outbound", "password": "password123"},
                )
                headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(
                        owner_id=1,
                        case_key="accepted-outbound-case",
                        customer_name="周先生",
                        subject="采纳建议",
                        status="pending",
                        priority="normal",
                    )
                    db.add(case)
                    db.flush()
                    suggestion = ReplySuggestion(
                        case_id=case.id,
                        requested_by=1,
                        status="completed",
                        content="这是一条经人工确认后发送的建议。",
                        citations_json="[]",
                        risk_flags_json="[]",
                        model_id="test-model",
                        prompt_version="test-v1",
                    )
                    db.add(suggestion)
                    db.commit()
                    case_id, suggestion_id = case.id, suggestion.id

                response = await client.post(
                    f"/api/v1/support/cases/{case_id}/suggestions/{suggestion_id}/decision",
                    headers=headers,
                    json={"decision": "accepted"},
                )
                workspace = await client.get(
                    f"/api/v1/support/cases/{case_id}/workspace", headers=headers
                )

                assert response.status_code == 200
                assert len(workspace.json()["data"]["outboundMessages"]) == 1
                assert workspace.json()["data"]["outboundMessages"][0]["deliveryClaim"] == "simulated"

    asyncio.run(scenario())


def test_manual_reply_cannot_bypass_high_risk_suggestion_gate(tmp_path):
    """风险策略下沉最终出口：存在未决策的高风险 AI 建议时，manual reply 也被拒。"""
    from app.framework.database import Base, Database
    from app.framework.errors import AppError
    from app.modules.support.models import ReplySuggestion, SupportCase
    from app.modules.support.outbound import OutboundService, build_customer_channel
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'outbound-gate.db'}")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username="gate-owner", password_hash="x", role="admin")
        db.add(owner)
        db.flush()
        case = SupportCase(
            owner_id=owner.id, case_key="gate-1", customer_name="顾客", subject="食品安全"
        )
        db.add(case)
        db.flush()
        db.add(
            ReplySuggestion(
                case_id=case.id,
                requested_by=owner.id,
                status="ready",
                content="建议退款并致歉。",
                risk_flags_json='["high_risk_food_safety"]',
                model_id="test",
                prompt_version="v1",
            )
        )
        db.commit()
        service = OutboundService(build_customer_channel())
        try:
            service.confirm(
                db,
                owner_id=owner.id,
                case_id=case.id,
                actor_id=owner.id,
                content="已为您办理退款。",
                expected_version=case.version,
                idempotency_key="manual-bypass-1",
            )
            raise AssertionError("高风险建议未决策时应拒绝 manual reply")
        except AppError as exc:
            assert exc.code == "HIGH_RISK_REQUIRES_ESCALATION"
            assert exc.status_code == 403
