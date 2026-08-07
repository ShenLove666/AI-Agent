from __future__ import annotations

import asyncio
import os
import tempfile

import httpx

from app.api.dashboard import _commerce_intent


def test_commerce_intent_baseline_is_explainable():
    assert _commerce_intent("我的外卖订单什么时候配送？") == "订单物流"
    assert _commerce_intent("顾客想申请退款售后") == "售后服务"
    assert _commerce_intent("这个商品还有库存吗") == "商品咨询"
    assert _commerce_intent("如何配置满减优惠活动") == "营销活动"
    assert _commerce_intent("今天天气如何") == "其他咨询"


def test_operations_dashboard_empty_dataset_contract():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/operations.db"
            from app.application import create_app
            from app.framework.database import Database
            from app.modules.users.models import User
            from app.modules.users.service import AuthService

            database = Database()
            database.create_schema()
            with database.session_factory() as db:
                db.add(
                    User(
                        username="operations-admin",
                        password_hash=AuthService(None).passwords.hash("password123"),
                        role="admin",
                    )
                )
                db.commit()

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "operations-admin", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    response = await client.get(
                        "/api/v1/admin/dashboard/operations?window=7d",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert response.status_code == 200, response.text
            payload = response.json()["data"]
            assert payload["kpis"]["merchantAccounts"] == 1
            assert payload["kpis"]["aiResponses"] == 0
            assert payload["kpis"]["positiveRate"] == 0
            assert payload["kpis"]["knowledgeHitRate"] == 0
            assert payload["intentDistribution"] == []
            assert len(payload["issues"]) == 4

    asyncio.run(scenario())
