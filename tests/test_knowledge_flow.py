from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx

from app.modules.retrieval.models import RetrievalRequest


def test_document_ingestion_and_user_isolated_retrieval():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/test.db"
            os.environ["UPLOAD_DIR"] = f"{directory}/uploads"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "owner", "password": "password123"},
                    )
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "owner", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    created = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "外贸知识库"},
                        headers=headers,
                    )
                    base_id = created.json()["data"]["id"]
                    uploaded = await client.post(
                        f"/api/v1/knowledge-bases/{base_id}/documents",
                        files={"file": ("customs.txt", "报关流程包括申报、查验、征税和放行。")},
                        headers=headers,
                    )
                    assert uploaded.status_code == 202
                    markdown_uploaded = await client.post(
                        f"/api/v1/knowledge-bases/{base_id}/documents",
                        files={
                            "file": (
                                "merchant-guide.markdown",
                                "# 商家指南\n\n报关资料需要提前核对。",
                            )
                        },
                        headers=headers,
                    )
                    assert markdown_uploaded.status_code == 202

                    documents = await client.get(
                        f"/api/v1/knowledge-bases/{base_id}/documents", headers=headers
                    )
                    assert all(
                        item["status"] == "indexed" for item in documents.json()["data"]
                    )

            owner_results = await app.state.container.retrieval.retrieve(
                RetrievalRequest("报关流程", metadata={"user_id": 1})
            )
            other_results = await app.state.container.retrieval.retrieve(
                RetrievalRequest("报关流程", metadata={"user_id": 999})
            )
            assert owner_results.results[0].source == "customs.txt"
            assert not other_results.results

    asyncio.run(scenario())
