from __future__ import annotations

import asyncio

import httpx

from app.framework.config import Settings
from app.modules.support.models import SupportCase, SupportMessage


def test_support_case_api_contract(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/v1/auth/register", json={"username": "agent", "password": "password123"})
                login = await client.post("/api/v1/auth/login", json={"username": "agent", "password": "password123"})
                token = login.json()["data"]["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(owner_id=1, case_key="api-1", customer_name="顾客", subject="配送超时", status="pending", priority="high")
                    db.add(case); db.flush()
                    db.add(SupportMessage(case_id=case.id, role="customer", content="订单迟到了")); db.commit()
                    case_id = case.id
                listed = await client.get("/api/v1/support/cases?status=pending&priority=high", headers=headers)
                assert listed.status_code == 200
                assert listed.json()["data"][0]["caseKey"] == "api-1"
                assigned = await client.post(f"/api/v1/support/cases/{case_id}/assign", headers=headers, json={"assigneeId": 1, "expectedVersion": 1})
                assert assigned.status_code == 200
                assert assigned.json()["data"]["status"] == "in_progress"
                replied = await client.post(f"/api/v1/support/cases/{case_id}/replies", headers=headers, json={"content": "已联系骑手核实"})
                assert replied.status_code == 200
                assert replied.json()["data"]["messages"][-1]["sentToCustomer"] is True
                metrics = await client.get("/api/v1/support/metrics", headers=headers)
                assert metrics.status_code == 200
                assert metrics.json()["data"]["totalCases"] == 1

    asyncio.run(scenario())
