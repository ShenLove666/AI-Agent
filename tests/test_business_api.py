from __future__ import annotations

import asyncio
import os
import tempfile

import httpx


def test_auth_and_conversation_flow():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/test.db"
            from app.application import create_app

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    register = await client.post(
                        "/api/v1/auth/register",
                        json={"username": "tester", "password": "password123"},
                    )
                    assert register.status_code == 201

                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "tester", "password": "password123"},
                    )
                    assert login.status_code == 200
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    current = await client.get("/api/v1/auth/me", headers=headers)
                    assert current.status_code == 200
                    assert current.json()["data"]["role"] == "user"

                    samples = await client.get("/api/v1/rag/sample-questions", headers=headers)
                    assert samples.status_code == 200
                    assert samples.json()["data"] == []

                    created = await client.post(
                        "/api/v1/conversations",
                        json={"title": "外贸问答"},
                        headers=headers,
                    )
                    assert created.status_code == 201
                    conversation_id = created.json()["data"]["id"]

                    second = await client.post(
                        "/api/v1/conversations",
                        json={"title": "后创建会话"},
                        headers=headers,
                    )
                    assert second.status_code == 201

                    with app.state.container.database.session_factory() as db:
                        app.state.container.conversations.add_message(
                            db,
                            conversation_id=conversation_id,
                            user_id=1,
                            role="user",
                            content="让旧会话成为最近活跃会话",
                        )

                    renamed = await client.patch(
                        f"/api/v1/conversations/{conversation_id}",
                        json={"title": "退款政策咨询"},
                        headers=headers,
                    )
                    assert renamed.status_code == 200
                    assert renamed.json()["data"]["title"] == "退款政策咨询"

                    renamed_inactive = await client.patch(
                        f"/api/v1/conversations/{second.json()['data']['id']}",
                        json={"title": "只重命名、不改变聊天顺序"},
                        headers=headers,
                    )
                    assert renamed_inactive.status_code == 200

                    listed = await client.get("/api/v1/conversations", headers=headers)
                    assert listed.status_code == 200
                    assert listed.json()["data"][0]["id"] == conversation_id
                    assert listed.json()["data"][0]["title"] == "退款政策咨询"

                    deleted = await client.delete(
                        f"/api/v1/conversations/{conversation_id}", headers=headers
                    )
                    assert deleted.status_code == 204

    asyncio.run(scenario())
