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
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
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
                # 拆域后：confirm 不再创建 AI EvaluationRun（经营复测与 AI 评测分离），
                # 不存在「campaign_confirm 产生的 pending 评测」
                from app.modules.evaluation.models import EvaluationRun as _EvalRun

                with database.session_factory() as _db:
                    leftover = _db.scalars(
                        select(_EvalRun).where(
                            _EvalRun.config_snapshot_json.contains("campaign_confirm")
                        )
                    ).all()
                    assert leftover == []

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

                # 记录发布时刻（用于构造前后 7 天对称窗口内的订单时间戳）
                publish_moment = datetime.utcnow()

                # ① 无经营时间数据 → insufficient_data：不得标记已解决
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
                assert detail["businessVerificationRunId"] == run_id
                assert detail["changeVersion"] == "v3"
                assert detail["afterEvidence"]["origin"] == "business_verify"
                assert detail["afterEvidence"]["verificationRunId"] == run_id
                assert (
                    detail["businessVerificationRun"]["status"]
                    == "insufficient_data"
                )
                assert (
                    detail["businessVerificationRun"]["metricKey"]
                    == "cross_sell_adoption_rate"
                )
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "resolved"},
                )
                assert resp.status_code == 400
                assert "未得到有效结果" in resp.json()["error"]["message"]

                # ② 补上发布前后 7 天窗口内的订单时间戳 → 复测 completed → 可 resolved
                with database.session_factory() as db:
                    from app.modules.commerce.models import Basket

                    baskets = db.scalars(select(Basket)).all()
                    for index, basket in enumerate(baskets):
                        basket.ordered_at = (
                            publish_moment - timedelta(days=3)
                            if index % 2 == 0
                            else publish_moment + timedelta(days=1)
                        )
                    db.commit()
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/verify",
                    headers=owner,
                )
                assert resp.status_code == 200
                detail = (
                    await client.get(
                        f"/api/v1/retail/optimization-tasks/{task_id}", headers=owner
                    )
                ).json()["data"]
                assert detail["businessVerificationRun"]["status"] == "completed"
                assert detail["businessVerificationRun"]["beforeValue"] == 100.0
                assert detail["businessVerificationRun"]["afterValue"] == 100.0
                assert detail["businessVerificationRun"]["baselineSampleSize"] > 0
                assert detail["afterEvidence"]["beforePairedBasketRate"] == 100.0

                # 任务详情含来源与目标指标
                assert detail["targetMetric"] == "搭配购采用率"
                assert detail["beforeEvidence"]["origin"] == "campaign_confirm"

                # 经营效果复测有效 → 可流转 resolved
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


def test_campaign_task_without_rule_is_rejected_clearly(tmp_path):
    """campaign 任务缺失关联规则 → 明确拒绝（不得空指针/500）。

    FK 开启后「规则行被删」已被引用完整性拦截；无规则任务的拒绝语义
    在 verify_task 顶层显式给出。
    """
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'retail-missing-rule.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app
    from app.modules.commerce.service import RetailDataError, RetailService
    from app.modules.optimization.models import OptimizationTask

    app = create_app()
    database = app.state.container.database
    database.create_schema()
    users = _seed_users(database)
    with database.session_factory() as db:
        task = OptimizationTask(
            owner_id=users["owner"].id,
            source_type="campaign",
            source_id="1",
            title="缺规则任务",
            status="pending_verification",
            target_metric="搭配购采用率",
        )
        db.add(task)
        db.flush()
        task_id = task.id
        db.commit()
        with pytest.raises(RetailDataError) as exc:
            RetailService().verify_task(db, users["owner"].id, task_id)
        assert "没有关联的关联规则" in str(exc.value)
    database.engine.dispose()


def test_ai_evaluation_task_verification_closes_loop(tmp_path):
    """evaluation 来源任务：发起复测 → 后台重跑 AI 评测 → 失败清零后可 resolved。"""
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'retail-ai-verify.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app
    from app.modules.evaluation.models import (
        EvaluationCase,
        EvaluationDataset,
        EvaluationRun,
    )
    from app.modules.optimization.models import OptimizationTask

    app = create_app()
    database = app.state.container.database
    database.create_schema()
    users = _seed_users(database)
    with database.session_factory() as db:
        dataset = EvaluationDataset(
            owner_id=users["owner"].id, name="AI 复测集", is_demo=True
        )
        db.add(dataset)
        db.flush()
        db.add(
            EvaluationCase(
                dataset_id=dataset.id,
                case_key="verify-a",
                question="搭配购活动怎么参加？",
                category="活动口径",
                difficulty="medium",
                expected_points_json="[]",
                expected_document_keys_json="[]",
                should_refuse=False,
            )
        )
        source_run = EvaluationRun(
            owner_id=users["owner"].id,
            dataset_id=dataset.id,
            status="completed",
            config_snapshot_json='{"origin": "evaluation_failure", "runId": 1}',
            is_demo=True,
        )
        db.add(source_run)
        db.flush()
        task = OptimizationTask(
            owner_id=users["owner"].id,
            source_type="evaluation",
            source_id="1",
            title="评测失败复测任务",
            status="pending_verification",
            target_metric="评测通过率",
            ai_evaluation_run_id=source_run.id,
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
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/verify",
                    headers=owner,
                )
                assert resp.status_code == 200, resp.text
                run_id = resp.json()["data"]["runId"]
                assert resp.json()["data"]["status"] == "pending"
                detail = (
                    await client.get(
                        f"/api/v1/retail/optimization-tasks/{task_id}", headers=owner
                    )
                ).json()["data"]
                # 后台执行完成：证据写回，AI 评测复测关联更新
                assert detail["aiEvaluationRunId"] == run_id
                assert detail["afterEvidence"]["origin"] == "task_verify"
                assert detail["afterEvidence"]["failed"] == 0
                # 失败清零 → 可 resolved
                resp = await client.post(
                    f"/api/v1/retail/optimization-tasks/{task_id}/transition",
                    headers=owner,
                    json={"status": "resolved"},
                )
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "resolved"

    _run_scenario(app, database, scenario)
    database.engine.dispose()
