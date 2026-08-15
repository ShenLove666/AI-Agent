from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from sqlalchemy import select


class FakeVectorStore:
    def __init__(self) -> None:
        self.deleted_documents: list[int] = []

    async def delete_document(self, document_id: int) -> None:
        self.deleted_documents.append(document_id)


class FakeVectorIndexer:
    def __init__(self) -> None:
        self.store = FakeVectorStore()
        self.indexed: list[dict] = []

    async def index(self, **kwargs) -> None:
        self.indexed.append(kwargs)


def _create_test_app(directory: str):
    os.environ["DB_URL"] = f"sqlite:///{directory}/regressions.db"
    os.environ["UPLOAD_DIR"] = f"{directory}/uploads"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app
    from app.modules.users.models import User
    from app.modules.users.service import AuthService

    app = create_app()
    database = app.state.container.database
    database.create_schema()
    with database.session_factory() as db:
        db.add(
            User(
                username="admin",
                password_hash=AuthService(None).passwords.hash("password123"),
                role="admin",
            )
        )
        db.commit()
    return app


async def _login(client: httpx.AsyncClient, password: str = "password123") -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def test_frontend_contracts_auth_and_knowledge_state_are_real():
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = _create_test_app(directory)
            fake_indexer = FakeVectorIndexer()
            app.state.container.knowledge.vector_indexer = fake_indexer
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    headers = await _login(client)

                    unknown = await client.get("/api/v1/does-not-exist", headers=headers)
                    assert unknown.status_code == 404
                    assert unknown.headers["content-type"].startswith("application/json")
                    assert unknown.json()["error"]["code"] == "ROUTE_NOT_FOUND"

                    settings = (await client.get("/api/v1/rag/settings", headers=headers)).json()[
                        "data"
                    ]
                    assert {"version", "items", "audits"} <= settings.keys()
                    assert settings["version"] >= 1
                    keys = {item["key"] for item in settings["items"]}
                    assert "retrieval_candidate_limit" in keys
                    assert "deepseek_api_key" in keys

                    not_implemented = await client.get("/api/v1/agents", headers=headers)
                    assert not_implemented.status_code == 501
                    assert not_implemented.json()["error"]["code"] == "NOT_IMPLEMENTED"

                    from app.modules.knowledge.models import (
                        KnowledgeBase,
                        KnowledgeChunk,
                        KnowledgeDocument,
                    )
                    from app.modules.rag.trace_models import RagTraceNode, RagTraceRun

                    source_path = Path(directory) / "guide.txt"
                    source_path.write_text("报关流程与清关材料", encoding="utf-8")
                    with app.state.container.database.session_factory() as db:
                        base = KnowledgeBase(owner_id=1, name="测试知识库")
                        db.add(base)
                        db.flush()
                        document = KnowledgeDocument(
                            knowledge_base_id=base.id,
                            uploader_id=1,
                            filename="guide.txt",
                            file_type="txt",
                            storage_path=str(source_path),
                            file_size=source_path.stat().st_size,
                            status="ready",
                            enabled=True,
                        )
                        db.add(document)
                        db.flush()
                        chunk = KnowledgeChunk(
                            knowledge_base_id=base.id,
                            document_id=document.id,
                            position=0,
                            content="报关流程需要准备清关材料",
                            enabled=True,
                        )
                        db.add(chunk)
                        trace = RagTraceRun(
                            id="trace-regression",
                            user_id=1,
                            conversation_id=None,
                            query="测试",
                            status="success",
                        )
                        db.add(trace)
                        db.flush()
                        db.add(
                            RagTraceNode(
                                run_id=trace.id,
                                name="retrieval",
                                status="success",
                                elapsed_ms=2.5,
                            )
                        )
                        db.commit()
                        document_id = document.id
                        chunk_id = chunk.id

                    schema_response = await client.get(
                        "/api/v1/knowledge-base/docs/ingestion-spec-schema",
                        headers=headers,
                    )
                    schema = schema_response.json()["data"]
                    assert {
                        "parseProfileLabel",
                        "parseProfiles",
                        "parseProfileExtensions",
                        "budgetFields",
                        "wholeDocumentSentinel",
                    } == schema.keys()
                    assert schema["parseProfileExtensions"] == ["csv", "xlsx"]

                    disabled = await client.patch(
                        f"/api/v1/knowledge-base/docs/{document_id}/chunks/batch-enable",
                        params={"value": "false"},
                        json={"chunkIds": [str(chunk_id)]},
                        headers=headers,
                    )
                    assert disabled.status_code == 200, disabled.text
                    assert disabled.json()["data"]["updated"] == 1
                    with app.state.container.database.session_factory() as db:
                        assert db.get(KnowledgeChunk, chunk_id).enabled is False
                    assert fake_indexer.store.deleted_documents == [document_id]
                    assert fake_indexer.indexed == []

                    detail = await client.get(
                        "/api/v1/rag/traces/runs/trace-regression", headers=headers
                    )
                    assert set(detail.json()["data"]) == {"run", "nodes"}
                    nodes = await client.get(
                        "/api/v1/rag/traces/runs/trace-regression/nodes", headers=headers
                    )
                    assert isinstance(nodes.json()["data"], list)
                    assert nodes.json()["data"][0]["nodeName"] == "retrieval"

                    changed = await client.put(
                        "/api/v1/user/password",
                        json={
                            "currentPassword": "password123",
                            "newPassword": "new-password-123",
                        },
                        headers=headers,
                    )
                    assert changed.status_code == 200
                    old_login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "password123"},
                    )
                    assert old_login.status_code == 401
                    await _login(client, "new-password-123")

    asyncio.run(scenario())


def test_chat_task_registry_enforces_owner():
    from app.modules.rag.task_registry import ChatTaskRegistry

    registry = ChatTaskRegistry()
    event = registry.register("task", owner_id=10)
    assert registry.cancel("task", owner_id=11) is False
    assert event.is_set() is False
    assert registry.cancel("task", owner_id=10) is True
    assert event.is_set() is True


def test_failed_document_is_excluded_from_keyword_retrieval():
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = _create_test_app(directory)
            from app.modules.knowledge.models import (
                KnowledgeBase,
                KnowledgeChunk,
                KnowledgeDocument,
            )
            from app.modules.knowledge.search import SqlKeywordSearchChannel
            from app.modules.retrieval.models import RetrievalRequest

            with app.state.container.database.session_factory() as db:
                base = KnowledgeBase(owner_id=1, name="检索一致性")
                db.add(base)
                db.flush()
                failed = KnowledgeDocument(
                    knowledge_base_id=base.id,
                    uploader_id=1,
                    filename="failed.txt",
                    file_type="txt",
                    storage_path="unused",
                    file_size=1,
                    status="failed",
                    enabled=True,
                )
                db.add(failed)
                db.flush()
                db.add(
                    KnowledgeChunk(
                        knowledge_base_id=base.id,
                        document_id=failed.id,
                        position=0,
                        content="仅失败文档包含的特殊关键词",
                        enabled=True,
                    )
                )
                db.commit()

            results = await SqlKeywordSearchChannel(
                app.state.container.database
            ).search(RetrievalRequest("特殊关键词", metadata={"user_id": 1}))
            assert results == []

    asyncio.run(scenario())


def test_document_reingestion_deletes_old_vectors_and_uses_database_chunk_ids():
    with tempfile.TemporaryDirectory() as directory:
        app = _create_test_app(directory)
        fake_indexer = FakeVectorIndexer()
        app.state.container.knowledge.vector_indexer = fake_indexer
        source_path = Path(directory) / "merchant-guide.txt"
        source_path.write_text("退款规则。" * 300, encoding="utf-8")

        from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument

        with app.state.container.database.session_factory() as db:
            base = KnowledgeBase(owner_id=1, name="商家规则")
            db.add(base)
            db.flush()
            document = KnowledgeDocument(
                knowledge_base_id=base.id,
                uploader_id=1,
                filename=source_path.name,
                file_type="txt",
                storage_path=str(source_path),
                file_size=source_path.stat().st_size,
                status="ready",
                enabled=True,
            )
            db.add(document)
            db.commit()
            document_id = document.id

            first = app.state.container.knowledge.ingest_document(db, document_id)
            assert first.status == "indexed"
            first_chunks = list(
                db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == document_id)
                    .order_by(KnowledgeChunk.position)
                )
            )
            assert len(first_chunks) > 1
            indexed_chunks = fake_indexer.indexed[-1]["chunks"]
            assert indexed_chunks == [
                (chunk.id, chunk.position, chunk.content) for chunk in first_chunks
            ]

            source_path.write_text("新的退款规则。", encoding="utf-8")
            second = app.state.container.knowledge.ingest_document(db, document_id)
            assert second.status == "indexed"
            second_chunks = list(
                db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
            )
            assert len(second_chunks) == 1

        assert fake_indexer.store.deleted_documents == [document_id, document_id]
