"""/health 版本信息契约测试。

覆盖：data 包含启动时缓存的 gitCommit（git 短提交号，失败回退 GIT_COMMIT /
"unknown"）与 frontendBuild（web/dist/index.html 的 mtime ISO，缺失 "unknown"）；
原有 status/application/environment/architecture/runtime 字段保持不变。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import httpx


def test_health_returns_version_info():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/health.db"
            from app.application import create_app

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    response = await client.get("/api/v1/health")
                    assert response.status_code == 200
                    data = response.json()["data"]
                    # 原有字段保持不变
                    assert data["status"] == "up"
                    assert data["application"]
                    assert data["environment"]
                    assert data["architecture"] == "modular-monolith"
                    assert data["runtime"] == "python"
                    # 版本信息：git 短提交号（git 仓库内运行应为真实 sha）
                    assert isinstance(data["gitCommit"], str)
                    assert data["gitCommit"]
                    # 前端产物构建时间：ISO 字符串或 "unknown"（无 dist 时）
                    assert isinstance(data["frontendBuild"], str)
                    assert data["frontendBuild"]

    asyncio.run(scenario())
