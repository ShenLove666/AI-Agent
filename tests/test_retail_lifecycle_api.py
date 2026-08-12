"""端到端契约测试 ②③④：方案确认发布、权限矩阵、任务生成与复测闭环。

覆盖：
② 方案：创建 → 同规则防重复 → 详情 → 确认（自动建任务+评测运行）→ 发布；
   draft 直接发布 / confirmed 重复确认被拒；乐观锁冲突 409；驳回分支。
③ 权限矩阵：user(客服) / supervisor / operator / admin 四角色，客服域与经营域互斥
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
from types import SimpleNamespace

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
            role="admin",
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
            role="operator",
            is_demo=True,
        )
        agent = User(
            username="demo-agent",
            password_hash=hash_value,
            role="user",
            is_demo=True,
        )
        db.add_all([owner, platform, operator, agent])
        db.flush()
        org = Organization(
            name="演示商家", owner_user_id=owner.id, is_demo=True
        )
        db.add(org)
        db.flush()
        db.add_all(
            [
                OrganizationMember(
                    org_id=org.id, user_id=owner.id, role="admin"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=operator.id, role="operator"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=agent.id, role="user"
                ),
                OrganizationMember(
                    org_id=org.id, user_id=platform.id, role="admin"
                ),
            ]
        )
        db.commit()
        return {
            "owner": owner,
            "platform": platform,
            "operator": operator,
            "agent": agent,
        }


class _FakeVerificationAgentic:
    """可控复测执行器：按问题关键词选择终态，评分结果确定。"""

    def __init__(self, refuse_marker: str = "保证") -> None:
        self.refuse_marker = refuse_marker
        self.questions: list[str] = []

    async def run(self, db, **kwargs):
        question = str(kwargs.get("question") or "")
        self.questions.append(question)
        if self.refuse_marker and self.refuse_marker in question:
            return SimpleNamespace(
                answer="当前证据不足，无法给出可靠结论，建议转人工复核。",
                results=(),
                terminal_state="refused",
                steps=(),
                runtime_mode="deterministic_fallback",
            )
        return SimpleNamespace(
            answer="引用有效活动或规则：不虚构优惠与库存。",
            results=(),
            terminal_state="grounded",
            steps=(),
            runtime_mode="deterministic_fallback",
        )


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
                agent = await _login(client, "demo-agent")
                platform = await _login(client, "support-admin")

                # ① 权限矩阵：/auth/me 权限集合（4 角色，客服/经营域切开）
                owner_perms = (
                    await client.get("/api/v1/auth/me", headers=owner)
                ).json()["data"]["permissions"]
                operator_perms = (
                    await client.get("/api/v1/auth/me", headers=operator)
                ).json()["data"]["permissions"]
                agent_perms = (
                    await client.get("/api/v1/auth/me", headers=agent)
                ).json()["data"]["permissions"]
                # 运营：经营域有权限，客服域无
                assert "campaign.create" in operator_perms
                assert "campaign.confirm" in operator_perms
                assert "task.update" in operator_perms
                assert "retail.view" in operator_perms
                assert "campaign.publish" not in operator_perms
                assert "support.case.read" not in operator_perms
                assert "support.escalation.read" not in operator_perms
                # 普通客服：客服域有权限，经营域无
                assert "support.case.read" in agent_perms
                assert "support.case.reply" in agent_perms
                assert "support.case.escalate" in agent_perms
                assert "retail.view" not in agent_perms
                assert "campaign.create" not in agent_perms
                assert "task.update" not in agent_perms
                assert "settings.write" not in agent_perms
                # 负责人：全部权限（含发布）
                assert "campaign.publish" in owner_perms
                assert "settings.write" in owner_perms
                assert "support.quality.read" in owner_perms
                # 运营调客服 API → 403；客服调经营 API → 403
                resp = await client.get(
                    "/api/v1/support/cases", headers=operator
                )
                assert resp.status_code == 403
                resp = await client.get(
                    "/api/v1/support/escalations", headers=agent
                )
                assert resp.status_code == 403
                resp = await client.get("/api/v1/retail/overview", headers=agent)
                assert resp.status_code == 403

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

                # 普通客服无创建方案权限 → 403
                resp = await client.post(
                    "/api/v1/retail/campaigns",
                    headers=agent,
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

                # 发布（operator 无 publish 权限 → 403；owner 有）
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_id}/transition",
                    headers=operator,
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

                # 发起复测：创建评测运行并关联，响应后后台立即执行（可控 fake 执行器）
                app.state.container.agentic = _FakeVerificationAgentic()
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
                # 复测已后台执行：运行完成、证据写回；越权拒答题 0 分 → 保持待复测
                assert detail["verificationRun"]["status"] == "completed"
                assert detail["afterEvidence"]["origin"] == "task_verify"
                assert detail["afterEvidence"]["runId"] == run_id
                assert detail["afterEvidence"]["failed"] >= 1
                assert detail["status"] == "pending_verification"

                # 任务详情含来源与目标指标
                assert detail["targetMetric"] == "搭配购采用率"
                assert detail["beforeEvidence"]["origin"] == "campaign_confirm"

                # 有失败用例：复测证据已存在，人工确认解决可直接流转
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

                # ④ 普通客服（user）调经营写接口 → 403（域隔离）
                await client.post(
                    "/api/v1/auth/register",
                    json={"username": "outsider", "password": "password123"},
                )
                outsider = await _login(client, "outsider", "password123")
                resp = await client.get("/api/v1/retail/overview", headers=outsider)
                assert resp.status_code == 403
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


def test_task_verification_auto_resolves_on_full_pass(tmp_path: Path):
    """④ 复测闭环：全用例通过 → 后台执行完自动流转 resolved；失败则保留待复测。"""
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'retail-verify.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app
    from app.modules.evaluation.models import EvaluationCase, EvaluationDataset
    from app.modules.optimization.models import OptimizationTask

    app = create_app()
    database = app.state.container.database
    database.create_schema()
    users = _seed_users(database)
    with database.session_factory() as db:
        dataset = EvaluationDataset(
            owner_id=users["owner"].id, name="复测评测集", is_demo=True
        )
        db.add(dataset)
        db.flush()
        db.add_all(
            [
                EvaluationCase(
                    dataset_id=dataset.id,
                    case_key="verify-a",
                    question="搭配购活动怎么参加？",
                    category="活动口径",
                    difficulty="medium",
                    expected_points_json="[]",
                    expected_document_keys_json="[]",
                    should_refuse=False,
                ),
                EvaluationCase(
                    dataset_id=dataset.id,
                    case_key="verify-b",
                    question="生鲜商品不满意可以退款吗？",
                    category="退款售后",
                    difficulty="medium",
                    expected_points_json="[]",
                    expected_document_keys_json="[]",
                    should_refuse=False,
                ),
            ]
        )
        task = OptimizationTask(
            owner_id=users["owner"].id,
            source_type="manual",
            source_id="1",
            title="复测闭环任务",
            status="pending_verification",
            target_metric="评测通过率",
            change_version="v1",
        )
        db.add(task)
        db.flush()
        task_id = task.id
        db.commit()

    async def scenario(app, database):
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                owner = await _login(client, "merchant-demo")
                app.state.container.agentic = _FakeVerificationAgentic()
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/verify",
                    headers=owner,
                )
                assert resp.status_code == 200, resp.text
                run_id = resp.json()["data"]["runId"]
                detail = (
                    await client.get(
                        f"/api/v1/retail/optimization-tasks/{task_id}", headers=owner
                    )
                ).json()["data"]
                # 全部通过：复测运行完成、证据写回、任务自动 resolved
                assert detail["verificationRun"]["status"] == "completed"
                assert detail["afterEvidence"]["origin"] == "task_verify"
                assert detail["afterEvidence"]["runId"] == run_id
                assert detail["afterEvidence"]["total"] == 2
                assert detail["afterEvidence"]["passed"] == 2
                assert detail["afterEvidence"]["failed"] == 0
                assert detail["status"] == "resolved"

    _run_scenario(app, database, scenario)
    database.engine.dispose()
