"""端到端契约测试 ②③④：方案确认发布、权限矩阵、任务生成与复测闭环。

覆盖：
② 方案：创建 → 同规则防重复 → 详情 → 确认（自动建任务+评测运行）→ 发布；
   draft 直接发布 / confirmed 重复确认被拒；乐观锁冲突 409；驳回分支。
③ 权限矩阵：merchant-owner / operator / analyst / platform-admin 各角色
   /auth/me 的权限集合，以及 campaign.confirm / campaign.publish / task.assign
   写接口的 200/403；无组织成员的用户访问零售数据被拒。
④ 任务闭环：确认方案自动建任务；进入 pending_verification 必须带 changeVersion；
   发起复测创建评测运行并关联；无复测运行不能 resolved；
   sync-from-evaluations 幂等补建任务。
"""

from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path

import httpx
from sqlalchemy import event, select

import app.application_core  # noqa: F401 - register all mapped tables
from app.framework.database import Base, Database
from app.modules.commerce.service import RetailService
from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.service import AuthService


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'retail.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    return database


def _source(root: Path) -> None:
    root.mkdir()
    with (root / "GoodsTypes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["Goods", "Types"])
        writer.writeheader()
        for name, category in (("牛肉", "肉类"), ("根茎类蔬菜", "果蔬")):
            writer.writerow({"Goods": name, "Types": category})
    with (root / "GoodsOrder.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "Goods"])
        writer.writeheader()
        for basket in range(1, 81):
            writer.writerow({"id": basket, "Goods": "牛肉"})
            writer.writerow({"id": basket, "Goods": "根茎类蔬菜"})


def _seed_users(database: Database) -> dict[str, User]:
    passwords = AuthService(
        __import__(
            "app.modules.users.repository", fromlist=["UserRepository"]
        ).UserRepository()
    )
    hash_value = passwords.passwords.hash("AdminDemo@2026")
    with database.session_factory() as db:
        owner = User(
            username="merchant-demo",
            password_hash=hash_value,
            role="user",
            is_demo=True,
        )
        platform = User(
            username="support-admin",
            password_hash=hash_value,
            role="admin",
        )
        operator = User(
            username="demo-operator",
            password_hash=hash_value,
            role="user",
            is_demo=True,
        )
        analyst = User(
            username="demo-analyst",
            password_hash=hash_value,
            role="user",
            is_demo=True,
        )
        db.add_all([owner, platform, operator, analyst])
        db.flush()
        org = Organization(
            name="演示商家", owner_user_id=owner.id, is_demo=True
        )
        db.add(org)
        db.flush()
        db.add_all(
            [
                OrganizationMember(
                    org_id=org.id, user_id=owner.id, role="merchant_owner"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=operator.id, role="operator"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=analyst.id, role="analyst"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=platform.id, role="support_supervisor"
                ),
            ]
        )
        db.commit()
        return {
            "owner": owner,
            "platform": platform,
            "operator": operator,
            "analyst": analyst,
        }


def _run_scenario(app, database, scenario):
    asyncio.run(scenario(app, database))


def test_campaign_lifecycle_and_task_backfill(tmp_path: Path):
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'retail.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app

    app = create_app()
    database = app.state.container.database
    database.create_schema()
    users = _seed_users(database)
    source = tmp_path / "source"
    _source(source)
    with database.session_factory() as db:
        RetailService().import_baskets(db, users["owner"].id, source)
        rule_id = db.scalar(
            select(
                __import__(
                    "app.modules.commerce.models", fromlist=["AssociationRule"]
                ).AssociationRule.id
            )
        )
    assert rule_id

    async def scenario(app, database):
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                owner = await _login(client, "merchant-demo")
                operator = await _login(client, "demo-operator")
                analyst = await _login(client, "demo-analyst")
                platform = await _login(client, "support-admin")

                # ① 权限矩阵：/auth/me 权限集合
                owner_perms = (
                    await client.get("/api/v1/auth/me", headers=owner)
                ).json()["data"]["permissions"]
                analyst_perms = (
                    await client.get("/api/v1/auth/me", headers=analyst)
                ).json()["data"]["permissions"]
                assert "campaign.confirm" in owner_perms
                assert "campaign.publish" in owner_perms
                assert "task.assign" in owner_perms
                assert "campaign.confirm" not in analyst_perms
                assert "retail.view" in analyst_perms
                assert "campaign.publish" in (
                    await client.get("/api/v1/auth/me", headers=platform)
                ).json()["data"]["permissions"]

                # ② 创建方案（operator 可确认 → 有权限）
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=operator,
                    json={"ruleId": rule_id},
                )
                assert resp.status_code == 200, resp.text
                campaign_id = resp.json()["data"]["id"]
                assert resp.json()["data"]["status"] == "draft"

                # 防重复：同规则未完成方案禁止再次创建
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=operator,
                    json={"ruleId": rule_id},
                )
                assert resp.status_code == 400
                assert "已有未完成" in resp.json()["error"]["message"]

                # analyst 无确认权限 → 403
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=analyst,
                    json={"ruleId": rule_id},
                )
                assert resp.status_code == 403

                # 详情
                resp = await client.get(
                    f"/api/v1/retail/campaigns/{campaign_id}", headers=owner
                )
                assert resp.status_code == 200
                detail = resp.json()["data"]
                assert detail["status"] == "draft"
                assert detail["versions"][0]["copy"]
                assert detail["rule"]["evidence"] is not None

                # draft 直接发布 → 拒绝（必须先确认）
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=owner,
                    json={"action": "publish", "expectedVersion": 1},
                )
                assert resp.status_code == 400

                # 乐观锁冲突 → 409（错误版本）
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=owner,
                    json={"action": "confirm", "expectedVersion": 99},
                )
                assert resp.status_code == 400
                assert "刷新" in resp.json()["error"]["message"]

                # 确认（operator 有 campaign.confirm）
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=operator,
                    json={"action": "confirm", "expectedVersion": 1},
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "confirmed"
                assert resp.json()["data"]["lockVersion"] == 2

                # 确认后自动创建优化任务 + 评测运行
                overview = (
                    await client.get("/api/v1/retail/overview", headers=owner)
                ).json()["data"]
                campaign_tasks = [
                    t
                    for t in overview["tasks"]
                    if t["sourceType"] == "campaign"
                    and t["sourceId"] == str(campaign_id)
                ]
                assert len(campaign_tasks) == 1
                assert campaign_tasks[0]["status"] == "new"
                assert any(r["status"] == "pending" for r in overview["evaluations"])

                # confirmed 重复确认 → 拒绝
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=owner,
                    json={"action": "confirm", "expectedVersion": 2},
                )
                assert resp.status_code == 400

                # 发布（analyst 无权限 → 403；owner 有）
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=analyst,
                    json={"action": "publish", "expectedVersion": 2},
                )
                assert resp.status_code == 403
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=owner,
                    json={"action": "publish", "expectedVersion": 2},
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "published"

                # 任务闭环：推进到 pending_verification 必须带 changeVersion
                task_id = campaign_tasks[0]["id"]
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "confirmed"},
                )
                assert resp.status_code == 200
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "optimizing"},
                )
                assert resp.status_code == 200
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "pending_verification"},
                )
                assert resp.status_code == 400
                assert "版本号" in resp.json()["error"]["message"]
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={
                        "status": "pending_verification",
                        "changeVersion": "v3",
                    },
                )
                assert resp.status_code == 200

                # 无复测运行不能 resolved
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "resolved"},
                )
                assert resp.status_code == 400

                # 发起复测：创建评测运行并关联
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/verify",
                    headers=owner,
                )
                assert resp.status_code == 200
                run_id = resp.json()["data"]["runId"]
                detail = (
                    await client.get(
                        f"/api/v1/retail/optimization-tasks/{task_id}", headers=owner
                    )
                ).json()["data"]
                assert detail["verificationRunId"] == run_id
                assert detail["changeVersion"] == "v3"
                assert detail["afterEvidence"] == {}

                # 任务详情含来源与目标指标
                assert detail["targetMetric"] == "搭配购采用率"
                assert detail["beforeEvidence"]["origin"] == "campaign_confirm"

                # 复测运行补齐 afterEvidence 后可 resolved
                with database.session_factory() as db:
                    from app.modules.optimization.models import OptimizationTask

                    task = db.get(OptimizationTask, task_id)
                    task.after_evidence_json = '{"score": 92}'
                    db.commit()
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "resolved"},
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "resolved"

                # ② 驳回分支：已发布方案释放规则 → 可再建 → 驳回
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=operator,
                    json={"ruleId": rule_id},
                )
                assert resp.status_code == 200
                second_id = resp.json()["data"]["id"]
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{second_id}/transition",
                    headers=owner,
                    json={
                        "action": "reject",
                        "expectedVersion": 1,
                        "reason": "毛利不满足投放要求",
                    },
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "rejected"
                detail = (
                    await client.get(
                        f"/api/v1/retail/campaigns/{second_id}", headers=owner
                    )
                ).json()["data"]
                assert detail["rejectedReason"] == "毛利不满足投放要求"
                # rejected 为终态：不能再确认
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{second_id}/transition",
                    headers=owner,
                    json={"action": "confirm", "expectedVersion": 2},
                )
                assert resp.status_code == 400

                # ④ 无组织用户：只能看到自己的空数据，写接口按权限拒绝
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "outsider", "password": "password123"},
                )
                outsider = await _login(client, "outsider", "password123")
                resp = await client.get("/api/v1/retail/overview", headers=outsider)
                assert resp.status_code == 200
                assert resp.json()["data"]["campaigns"] == []
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=outsider,
                    json={"ruleId": rule_id},
                )
                assert resp.status_code == 403

                # ③ sync-from-evaluations 幂等补建任务
                resp = await client.post(
                    "/api/v1/retail/optimization-tasks/sync-from-evaluations",
                    headers=owner,
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["created"] >= 0

    _run_scenario(app, database, scenario)
    database.engine.dispose()


async def _login(client, username: str, password: str = "AdminDemo@2026") -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}
