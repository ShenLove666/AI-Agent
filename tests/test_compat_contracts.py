"""RAGent 前端契约兼容路由测试 (阶段 A 契约闭环)

覆盖: 单数 /knowledge-base 全套、Chunk 管理、用户管理、Trace 兼容、
停止生成、消息反馈、未实现模块 501 兜底。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import httpx


def _make_app_and_db(directory: str, admin_username: str = "admin", admin_password: str = "password123"):
    os.environ["DB_URL"] = f"sqlite:///{directory}/compat.db"
    from app.application import create_app
    from app.framework.database import Database
    from app.modules.users.models import User
    from app.modules.users.service import AuthService

    database = Database()
    database.create_schema()
    with database.session_factory() as db:
        db.add(
            User(
                username=admin_username,
                password_hash=AuthService(None).passwords.hash(admin_password),
                role="admin",
            )
        )
        db.commit()
    return create_app()


def test_knowledge_base_compat_contract():
    """单数 /knowledge-base 契约: 库 CRUD + 文档 + Chunk"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["UPLOAD_DIR"] = f"{directory}/uploads"
            app = _make_app_and_db(directory)
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    # 创建知识库 -> 返回 id 字符串
                    created = await client.post(
                        "/api/v1/knowledge-base",
                        json={"name": "外贸手册", "description": "测试"},
                        headers=headers,
                    )
                    assert created.status_code == 200, created.text
                    base_id = created.json()["data"]
                    assert isinstance(base_id, str)

                    # 分页列表 (PageResult 契约)
                    listed = await client.get(
                        "/api/v1/knowledge-base?current=1&size=10", headers=headers
                    )
                    body = listed.json()["data"]
                    assert {"records", "total", "current", "size"} <= set(body)
                    assert body["records"][0]["name"] == "外贸手册"
                    assert "createTime" in body["records"][0]
                    assert "documentCount" in body["records"][0]

                    # 详情 / 重命名
                    detail = await client.get(
                        f"/api/v1/knowledge-base/{base_id}", headers=headers
                    )
                    assert detail.json()["data"]["id"] == int(base_id)
                    renamed = await client.put(
                        f"/api/v1/knowledge-base/{base_id}",
                        json={"name": "外贸手册V2"},
                        headers=headers,
                    )
                    assert renamed.json()["data"]["name"] == "外贸手册V2"

                    # 上传文档
                    upload = await client.post(
                        f"/api/v1/knowledge-base/{base_id}/docs/upload",
                        headers=headers,
                        data={"sourceType": "local", "processMode": "auto"},
                        files={"file": ("guide.txt", "报关知识测试内容" * 10, "text/plain")},
                    )
                    assert upload.status_code == 200, upload.text
                    doc = upload.json()["data"]
                    assert doc["docName"] == "guide.txt"
                    assert doc["kbId"] == int(base_id)

                    unsupported = await client.post(
                        f"/api/v1/knowledge-base/{base_id}/docs/upload",
                        headers=headers,
                        data={"sourceType": "local", "processMode": "chunk"},
                        files={
                            "file": (
                                "fake.xls",
                                b"not-a-sheet",
                                "application/octet-stream",
                            )
                        },
                    )
                    assert unsupported.status_code == 415
                    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_TYPE"

                    previous_limit = os.environ.get("MAX_UPLOAD_FILE_SIZE")
                    os.environ["MAX_UPLOAD_FILE_SIZE"] = "8"
                    try:
                        oversized = await client.post(
                            f"/api/v1/knowledge-base/{base_id}/docs/upload",
                            headers=headers,
                            data={"sourceType": "local", "processMode": "chunk"},
                            files={"file": ("large.txt", b"more-than-eight-bytes", "text/plain")},
                        )
                    finally:
                        if previous_limit is None:
                            os.environ.pop("MAX_UPLOAD_FILE_SIZE", None)
                        else:
                            os.environ["MAX_UPLOAD_FILE_SIZE"] = previous_limit
                    assert oversized.status_code == 413
                    assert oversized.json()["error"]["code"] == "UPLOAD_TOO_LARGE"

                    # 文档列表字段契约
                    docs = await client.get(
                        f"/api/v1/knowledge-base/{base_id}/docs?current=1&size=10",
                        headers=headers,
                    )
                    record = docs.json()["data"]["records"][0]
                    assert {
                        "id", "kbId", "docName", "fileType", "fileSize",
                        "status", "chunkCount", "createTime",
                    } <= set(record)

                    # 文档搜索
                    search = await client.get(
                        "/api/v1/knowledge-base/docs/search?keyword=guide&limit=5",
                        headers=headers,
                    )
                    assert search.json()["data"][0]["docName"] == "guide.txt"

                    # 入库后 chunk 契约
                    from app.framework.database import Database
                    from app.modules.knowledge.service import KnowledgeService

                    service = KnowledgeService()
                    with Database().session_factory() as db:
                        service.ingest_document(db, doc["id"])

                    chunks = await client.get(
                        f"/api/v1/knowledge-base/docs/{doc['id']}/chunks?current=1&size=10",
                        headers=headers,
                    )
                    records = chunks.json()["data"]["records"]
                    assert len(records) >= 1
                    assert {"id", "kbId", "docId", "chunkIndex", "content", "enabled"} <= set(records[0])

                    # 编辑 chunk
                    edited = await client.put(
                        f"/api/v1/knowledge-base/docs/{doc['id']}/chunks/{records[0]['id']}",
                        json={"content": "修改后的分块内容"},
                        headers=headers,
                    )
                    assert edited.json()["data"]["content"] == "修改后的分块内容"

                    # 新建 chunk
                    new_chunk = await client.post(
                        f"/api/v1/knowledge-base/docs/{doc['id']}/chunks",
                        json={"content": "手动新增分块", "index": 99},
                        headers=headers,
                    )
                    assert new_chunk.status_code == 200
                    assert new_chunk.json()["data"]["chunkIndex"] == 99

                    # 删除 chunk
                    deleted_chunk = await client.delete(
                        f"/api/v1/knowledge-base/docs/{doc['id']}/chunks/{new_chunk.json()['data']['id']}",
                        headers=headers,
                    )
                    assert deleted_chunk.status_code == 200

                    # 预览 / 删除文档
                    preview = await client.get(
                        f"/api/v1/knowledge-base/docs/{doc['id']}/preview", headers=headers
                    )
                    assert preview.status_code == 200
                    assert "报关" in preview.json()["data"]

                    removed = await client.delete(
                        f"/api/v1/knowledge-base/docs/{doc['id']}", headers=headers
                    )
                    assert removed.status_code == 200

                    # 删除知识库
                    removed_base = await client.delete(
                        f"/api/v1/knowledge-base/{base_id}", headers=headers
                    )
                    assert removed_base.status_code == 200

    asyncio.run(scenario())


def test_user_management_and_admin_guard():
    """用户管理接口 + 普通用户越权 403"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            app = _make_app_and_db(directory)
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    # 普通用户
                    await client.post(
                        "/api/v1/auth/register",
                        json={"username": "worker", "password": "password123"},
                    )
                    worker_login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "worker", "password": "password123"},
                    )
                    worker_token = worker_login.json()["data"]["access_token"]
                    worker_headers = {"Authorization": f"Bearer {worker_token}"}

                    # 普通用户访问用户管理 -> 403
                    denied = await client.get("/api/v1/users", headers=worker_headers)
                    assert denied.status_code == 403

                    # 未实现的管理模块也必须先做权限校验，不向普通用户暴露能力边界
                    not_impl = await client.get("/api/v1/agents", headers=worker_headers)
                    assert not_impl.status_code == 403
                    body = not_impl.json()
                    assert body["success"] is False
                    assert body["error"]["code"] == "FORBIDDEN"

                    # 管理员
                    admin_login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "password123"},
                    )
                    admin_token = admin_login.json()["data"]["access_token"]
                    admin_headers = {"Authorization": f"Bearer {admin_token}"}

                    # 管理员创建用户
                    created = await client.post(
                        "/api/v1/users",
                        json={"username": "newbie", "password": "password123", "role": "user"},
                        headers=admin_headers,
                    )
                    assert created.status_code == 200
                    new_id = created.json()["data"]["id"]

                    # 提升为管理员
                    promoted = await client.put(
                        f"/api/v1/users/{new_id}",
                        json={"role": "admin"},
                        headers=admin_headers,
                    )
                    assert promoted.json()["data"]["role"] == "admin"

                    # 停用
                    disabled = await client.delete(
                        f"/api/v1/users/{new_id}", headers=admin_headers
                    )
                    assert disabled.json()["data"] is True

                    # 修改自己密码
                    changed = await client.put(
                        "/api/v1/user/password",
                        json={"currentPassword": "password123", "newPassword": "newpass12345"},
                        headers=admin_headers,
                    )
                    assert changed.status_code == 200

    asyncio.run(scenario())


def test_trace_feedback_and_stop_compat():
    """Trace 兼容契约 + 消息反馈 + 停止生成"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            app = _make_app_and_db(directory)
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    # Trace 分页契约 (空数据)
                    runs = await client.get(
                        "/api/v1/rag/traces/runs?current=1&size=10", headers=headers
                    )
                    body = runs.json()["data"]
                    assert {"records", "total", "size", "current", "pages"} <= set(body)
                    assert body["records"] == []

                    # 停止生成: 未注册任务 -> cancelled=false (幂等)
                    stopped = await client.post(
                        "/api/v1/rag/v3/stop?taskId=not-exist", headers=headers
                    )
                    assert stopped.status_code == 200
                    assert stopped.json()["data"]["cancelled"] is False

                    # 创建会话并写入助手消息, 验证反馈
                    conversation = await client.post(
                        "/api/v1/conversations", json={"title": "测试会话"}, headers=headers
                    )
                    conversation_id = conversation.json()["data"]["conversationId"]
                    assert conversation_id

                    # 直接写入一条助手消息 (绕过模型)
                    from app.framework.database import Database
                    from app.modules.conversations.models import Message

                    with Database().session_factory() as db:
                        message = Message(
                            conversation_id=conversation_id,
                            user_id=1,
                            role="assistant",
                            content="测试回答内容",
                            thinking_content="正在核对商家规则",
                            message_status="INTERRUPTED",
                            recommended_questions_json='["退款需要多久？"]',
                        )
                        db.add(message)
                        db.commit()
                        message_id = message.id

                    feedback = await client.post(
                        f"/api/v1/conversations/messages/{message_id}/feedback",
                        json={"vote": 1},
                        headers=headers,
                    )
                    assert feedback.status_code == 200
                    assert feedback.json()["data"]["vote"] == 1

                    history = await client.get(
                        f"/api/v1/conversations/{conversation_id}/messages",
                        headers=headers,
                    )
                    restored = history.json()["data"][0]
                    assert restored["vote"] == 1
                    assert restored["messageStatus"] == "INTERRUPTED"
                    assert restored["thinkingContent"] == "正在核对商家规则"
                    assert restored["recommendedQuestions"] == ["退款需要多久？"]
                    assert restored["recommendedQuestionsStatus"] == "NOT_REQUESTED"

                    cancel = await client.delete(
                        f"/api/v1/conversations/messages/{message_id}/feedback",
                        headers=headers,
                    )
                    assert cancel.json()["data"]["vote"] is None

                    # 推荐问题 (无模型时返回空列表而非报错)
                    recommended = await client.post(
                        f"/api/v1/conversations/messages/{message_id}/recommended-questions",
                        headers=headers,
                    )
                    assert recommended.status_code == 200
                    assert isinstance(recommended.json()["data"]["questions"], list)
                    assert recommended.json()["data"]["status"] in {
                        "SUCCESS",
                        "EMPTY",
                        "FAILED",
                    }
                    refreshed = await client.get(
                        f"/api/v1/conversations/{conversation_id}/messages",
                        headers=headers,
                    )
                    assert refreshed.json()["data"][0]["recommendedQuestions"] == recommended.json()[
                        "data"
                    ]["questions"]
                    assert refreshed.json()["data"][0]["recommendedQuestionsStatus"] == recommended.json()[
                        "data"
                    ]["status"]

    asyncio.run(scenario())


def test_all_frontend_service_roots_have_contracts():
    """前端所有 service 模块的根路径都有明确的 2xx/4xx/501 契约, 不出现未知 404"""

    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            app = _make_app_and_db(directory)
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": "admin", "password": "password123"},
                    )
                    token = login.json()["data"]["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    # 未实现的兼容端点返回真实 HTTP 501，已实现端点返回 200。
                    probe_roots = [
                        ("/api/v1/agents", 501),
                        ("/api/v1/admin/dashboard", 501),
                        ("/api/v1/biz-change-logs", 200),
                        ("/api/v1/ingestion/pipelines", 501),
                        ("/api/v1/intent-tree", 501),
                        ("/api/v1/admin/kg", 501),
                        ("/api/v1/mappings", 501),
                        ("/api/v1/sample-questions", 501),
                        ("/api/v1/rag/sample-questions", 200),
                        ("/api/v1/rag/settings", 200),      # 实现
                        ("/api/v1/users", 200),             # 实现
                        ("/api/v1/knowledge-base", 200),    # 实现
                        ("/api/v1/conversations", 200),     # 实现
                        ("/api/v1/rag/traces/runs", 200),   # 实现
                    ]
                    for path, expected in probe_roots:
                        response = await client.get(path, headers=headers)
                        assert response.status_code == expected, (
                            f"{path} -> {response.status_code} (期望 {expected})"
                        )

    asyncio.run(scenario())
