"""端到端契约测试 ①：系统设置可编辑（保存/版本冲突/白名单/审计/密钥脱敏）。

覆盖：
- GET /rag/settings 返回白名单项与全局版本
- PATCH 保存立即生效参数并返回新版本
- 版本冲突（expectedVersion 过期）返回 409
- 白名单外 key / 超范围值返回 400
- 密钥只显示 configured，不返回明文
- 审计记录含操作者、旧值、新值
- 无 settings.write 权限的用户 PATCH 返回 403
- /auth/me 返回 permissions 与商家归属
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx


def test_settings_patch_flow_and_audit(tmp_path: Path):
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'settings.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app
    from app.modules.users.models import User
    from app.modules.users.service import AuthService

    app = create_app()
    database = app.state.container.database
    database.create_schema()

    passwords = AuthService(__import__("app.modules.users.repository", fromlist=["UserRepository"]).UserRepository())
    with database.session_factory() as db:
        admin = User(
            username="settings-admin",
            password_hash=passwords.passwords.hash("AdminDemo@2026"),
            role="admin",
        )
        db.add(admin)
        db.commit()

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "settings-admin", "password": "AdminDemo@2026"},
                )
                token = login.json()["data"]["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                # 1. GET：白名单 + 版本 + 密钥脱敏
                resp = await client.get("/api/v1/rag/settings", headers=headers)
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert {"version", "items", "audits"} <= data.keys()
                items = {item["key"]: item for item in data["items"]}
                assert items["retrieval_candidate_limit"]["value"] >= 5
                assert items["deepseek_api_key"]["configured"] is False
                assert items["deepseek_api_key"]["value"] is None

                # 2. PATCH 保存立即生效参数
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=headers,
                    json={
                        "expectedVersion": data["version"],
                        "changes": [
                            {"key": "retrieval_candidate_limit", "value": 30},
                            {"key": "retrieval_context_limit", "value": 8},
                        ],
                        "resetKeys": [],
                    },
                )
                assert resp.status_code == 200, resp.text
                new_version = resp.json()["data"]["version"]
                assert new_version == data["version"] + 1

                # 3. 立即生效：重新 GET 看到新值
                resp = await client.get("/api/v1/rag/settings", headers=headers)
                items = {item["key"]: item for item in resp.json()["data"]["items"]}
                assert items["retrieval_candidate_limit"]["value"] == 30
                assert items["retrieval_candidate_limit"]["overridden"] is True
                assert items["retrieval_context_limit"]["value"] == 8

                # 4. 版本冲突 → 409
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=headers,
                    json={
                        "expectedVersion": data["version"],
                        "changes": [
                            {"key": "retrieval_candidate_limit", "value": 40}
                        ],
                        "resetKeys": [],
                    },
                )
                assert resp.status_code == 409
                assert resp.json()["error"]["code"] == "SETTINGS_VERSION_CONFLICT"

                # 5. 白名单外 key → 400
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=headers,
                    json={
                        "expectedVersion": new_version,
                        "changes": [{"key": "secret_internal_flag", "value": 1}],
                        "resetKeys": [],
                    },
                )
                assert resp.status_code == 400
                assert resp.json()["error"]["code"] == "SETTINGS_UNKNOWN_KEY"

                # 6. 超范围值 → 400
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=headers,
                    json={
                        "expectedVersion": new_version,
                        "changes": [
                            {"key": "retrieval_candidate_limit", "value": 9999}
                        ],
                        "resetKeys": [],
                    },
                )
                assert resp.status_code == 400
                assert resp.json()["error"]["code"] == "SETTINGS_INVALID_VALUE"

                # 7. 恢复默认
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=headers,
                    json={
                        "expectedVersion": new_version,
                        "changes": [],
                        "resetKeys": ["retrieval_candidate_limit"],
                    },
                )
                assert resp.status_code == 200
                new_version = resp.json()["data"]["version"]
                resp = await client.get("/api/v1/rag/settings", headers=headers)
                items = {item["key"]: item for item in resp.json()["data"]["items"]}
                assert items["retrieval_candidate_limit"]["overridden"] is False

                # 8. 审计包含操作者与旧值/新值（首次设置旧值为空，重置后应看到旧值）
                audits = resp.json()["data"]["audits"]
                update_audits = [a for a in audits if a["operation"] == "update"]
                assert any(
                    a["key"] == "retrieval_candidate_limit"
                    and a["operatorName"] == "settings-admin"
                    and a["newValue"]
                    for a in update_audits
                )
                resets = [a for a in audits if a["operation"] == "reset"]
                assert any(
                    a["key"] == "retrieval_candidate_limit"
                    and a["operatorName"] == "settings-admin"
                    and a["oldValue"]
                    for a in resets
                )

                # 9. 普通用户（无组织、无 settings.write）→ 403
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "plain-user", "password": "password123"},
                )
                plain_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "plain-user", "password": "password123"},
                )
                plain_headers = {
                    "Authorization": f"Bearer {plain_login.json()['data']['access_token']}"
                }
                resp = await client.patch(
                    "/api/v1/rag/settings",
                    headers=plain_headers,
                    json={
                        "expectedVersion": new_version,
                        "changes": [
                            {"key": "retrieval_candidate_limit", "value": 12}
                        ],
                        "resetKeys": [],
                    },
                )
                assert resp.status_code == 403

                # 10. /auth/me 返回 permissions 与商家归属
                me = (
                    await client.get("/api/v1/auth/me", headers=plain_headers)
                ).json()["data"]
                assert "permissions" in me
                # 无组织用户归属自己（不代理任何商家）
                assert me["merchantOwnerId"] == int(me["userId"])
                assert "settings.write" not in me["permissions"]

                me_admin = (
                    await client.get("/api/v1/auth/me", headers=headers)
                ).json()["data"]
                assert "settings.write" in me_admin["permissions"]
                assert "user.manage" in me_admin["permissions"]

    asyncio.run(scenario())


def test_settings_audit_never_exposes_secret_values(tmp_path: Path):
    """Secret setting audits remain useful without returning the secret itself."""
    from app.framework.config import Settings
    from app.modules.settings.repository import RuntimeSettingsRepository
    from app.modules.settings.service import RuntimeSettingsService

    database_url = f"sqlite:///{tmp_path / 'secret-audit.db'}"
    settings = Settings(database_url=database_url)
    from app.framework.database import Database

    database = Database(database_url)
    database.create_schema()
    service = RuntimeSettingsService(settings, RuntimeSettingsRepository())

    with database.session_factory() as db:
        service.apply(
            db,
            changes={"deepseek_api_key": "unit-test-secret-value"},
            reset_keys=[],
            expected_version=1,
            operator_id=None,
            operator_name="test-admin",
        )
        snapshot = service.snapshot(db)

    audit = next(item for item in snapshot["audits"] if item["key"] == "deepseek_api_key")
    assert audit["newValue"] == "已配置"
    assert "unit-test-secret-value" not in repr(snapshot)
