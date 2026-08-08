from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from app.framework.config import Settings
from app.modules.orders.models import Order, OrderItem
from app.modules.support.models import SupportCase, SupportMessage


def test_order_api_is_authenticated_and_owner_scoped(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'v3-api.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "order-owner", "password": "password123"},
                )
                owner_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "order-owner", "password": "password123"},
                )
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "order-outsider", "password": "password123"},
                )
                outsider_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "order-outsider", "password": "password123"},
                )
                owner_headers = {
                    "Authorization": f"Bearer {owner_login.json()['data']['access_token']}"
                }
                outsider_headers = {
                    "Authorization": f"Bearer {outsider_login.json()['data']['access_token']}"
                }
                with app.state.container.database.session_factory() as db:
                    order = Order(
                        owner_id=1,
                        order_no="NB-API-001",
                        status="paid",
                        total_amount_minor=4990,
                        placed_at=datetime(2026, 8, 8, 12, 0),
                        lineage_json='{"products":{"provenance":"observed"}}',
                    )
                    db.add(order)
                    db.flush()
                    db.add(
                        OrderItem(
                            order_id=order.id,
                            product_name="鲜牛奶",
                            quantity=1,
                            unit_price_minor=4990,
                        )
                    )
                    db.commit()

                anonymous = await client.get("/api/v1/orders/NB-API-001")
                visible = await client.get(
                    "/api/v1/orders/NB-API-001", headers=owner_headers
                )
                hidden = await client.get(
                    "/api/v1/orders/NB-API-001", headers=outsider_headers
                )

                assert anonymous.status_code == 401
                assert visible.status_code == 200
                assert visible.json()["data"]["items"][0]["productName"] == "鲜牛奶"
                assert hidden.status_code == 404
                assert hidden.json()["error"]["code"] == "ORDER_NOT_FOUND"

    asyncio.run(scenario())


def test_support_workspace_aggregates_linked_order_without_cross_owner_leak(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'workspace-api.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                for username in ("workspace-owner", "workspace-outsider"):
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": username, "password": "password123"},
                    )
                owner_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "workspace-owner", "password": "password123"},
                )
                outsider_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "workspace-outsider", "password": "password123"},
                )
                owner_headers = {
                    "Authorization": f"Bearer {owner_login.json()['data']['access_token']}"
                }
                outsider_headers = {
                    "Authorization": f"Bearer {outsider_login.json()['data']['access_token']}"
                }
                with app.state.container.database.session_factory() as db:
                    order = Order(
                        owner_id=1,
                        order_no="NB-WORKSPACE-001",
                        status="delivering",
                        total_amount_minor=7280,
                        is_demo=True,
                    )
                    db.add(order)
                    db.flush()
                    case = SupportCase(
                        owner_id=1,
                        order_id=order.id,
                        case_key="case-workspace-001",
                        customer_name="周女士",
                        subject="订单延误",
                        status="pending",
                        priority="high",
                        is_demo=True,
                    )
                    db.add(case)
                    db.flush()
                    db.add(
                        SupportMessage(
                            case_id=case.id,
                            role="customer",
                            content="我的订单什么时候送达？",
                        )
                    )
                    db.commit()
                    case_id = case.id

                visible = await client.get(
                    f"/api/v1/support/cases/{case_id}/workspace",
                    headers=owner_headers,
                )
                hidden = await client.get(
                    f"/api/v1/support/cases/{case_id}/workspace",
                    headers=outsider_headers,
                )

                assert visible.status_code == 200
                workspace = visible.json()["data"]
                assert workspace["case"]["caseKey"] == "case-workspace-001"
                assert workspace["order"]["orderNo"] == "NB-WORKSPACE-001"
                assert workspace["activeSuggestion"] is None
                assert workspace["outboundMessages"] == []
                assert workspace["diagnostics"] == {
                    "messageCount": 1,
                    "suggestionCount": 0,
                    "outboundCount": 0,
                }
                assert hidden.status_code == 404
                assert hidden.json()["error"]["code"] == "SUPPORT_CASE_NOT_FOUND"

    asyncio.run(scenario())
