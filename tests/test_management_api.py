from __future__ import annotations

import asyncio
import os
import tempfile

import httpx


def test_management_routes_and_spa_entry():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/management.db"
            from app.application import create_app
            from app.modules.users.models import User
            from app.framework.database import Database

            # 管理接口要求 admin: 直接初始化管理员用户
            from app.modules.users.service import AuthService

            database = Database()
            database.create_schema()
            with database.session_factory() as db:
                db.add(
                    User(
                        username="manager",
                        password_hash=AuthService(None).passwords.hash("password123"),
                        role="admin",
                    )
                )
                db.commit()

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    # 普通用户访问管理接口应 403
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "normal", "password": "password123"},
                    )
                    normal_login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "normal", "password": "password123"},
                    )
                    normal_token = normal_login.json()["data"]["access_token"]
                    forbidden = await client.get(
                        "/api/v1/management/models",
                        headers={"Authorization": f"Bearer {normal_token}"},
                    )
                    assert forbidden.status_code == 403

                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "manager", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    models = await client.get("/api/v1/management/models", headers=headers)
                    assert models.status_code == 200
                    assert "retrievalChannels" in models.json()["data"]

                    settings = await client.get("/api/v1/management/settings", headers=headers)
                    assert settings.status_code == 200
                    assert settings.json()["data"]["features"]["ragTrace"] is True

                    traces = await client.get("/api/v1/management/traces", headers=headers)
                    assert traces.status_code == 200
                    assert traces.json()["data"] == []

                    for path in ("/", "/chat"):
                        page = await client.get(path)
                        assert page.status_code == 200
                        assert '<div id="root"></div>' in page.text

    asyncio.run(scenario())
