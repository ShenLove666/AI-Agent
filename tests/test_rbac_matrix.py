"""RBAC 越权矩阵测试：4 角色 × 11 类 API + 跨组织 404。

矩阵（200=允许，403=拒绝）：
| API                          | 客服 | 主管 | 运营 | Admin |
| GET /support/cases           | 200  | 200  | 403  | 200   |
| POST /support/.../replies    | 403¹ | 200  | 403  | 200   |
| GET /support/escalations     | 403  | 200  | 403  | 200   |
| POST escalation resolve      | 403  | 200  | 403  | 200   |
| GET /retail/overview         | 403  | 403  | 200  | 200   |
| POST /retail/campaigns       | 403  | 403  | 200  | 200   |
| campaign confirm             | 403  | 403  | 200  | 200   |
| campaign publish             | 403  | 403  | 403  | 200   |
| GET /knowledge-bases         | 403  | 403  | 403  | 200   |
| PATCH /rag/settings          | 403  | 403  | 403  | 200   |
| GET /users                   | 403  | 403  | 403  | 200   |

跨组织：商家 B 的资源对商家 A 的运营 → 404（不暴露存在性）。
"""

from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path

import httpx
from sqlalchemy import event, select

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.modules.commerce.service import RetailService
from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.service import AuthService


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'rbac.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    return database


def _source(root: Path) -> None:
    root.mkdir()
    with (root / "GoodsTypes.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Goods", "Types"])
        writer.writeheader()
        for name, category in (
            ("牛肉", "肉类"),
            ("根茎类蔬菜", "果蔬"),
            ("全脂牛奶", "乳制品"),
            ("香草", "调味品"),
        ):
            writer.writerow({"Goods": name, "Types": category})
    with (root / "GoodsOrder.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "Goods"])
        writer.writeheader()
        for basket in range(1, 81):
            writer.writerow({"id": basket, "Goods": "牛肉"})
            writer.writerow({"id": basket, "Goods": "根茎类蔬菜"})
            if basket <= 60:
                writer.writerow({"id": basket, "Goods": "全脂牛奶"})
                writer.writerow({"id": basket, "Goods": "香草"})


def _seed_org(
    db, prefix: str, password_hash: str
) -> dict[str, User]:
    owner = User(
        username=f"{prefix}-admin",
        password_hash=password_hash,
        role="admin",
    )
    supervisor = User(
        username=f"{prefix}-supervisor",
        password_hash=password_hash,
        role="supervisor",
    )
    operator = User(
        username=f"{prefix}-operator",
        password_hash=password_hash,
        role="operator",
    )
    agent = User(
        username=f"{prefix}-user",
        password_hash=password_hash,
        role="user",
    )
    db.add_all([owner, supervisor, operator, agent])
    db.flush()
    org = Organization(
        name=f"{prefix} 商家", owner_user_id=owner.id, is_demo=True
    )
    db.add(org)
    db.flush()
    db.add_all(
        [
            OrganizationMember(org_id=org.id, user_id=owner.id, role="admin"),
            OrganizationMember(
                org_id=org.id, user_id=supervisor.id, role="supervisor"
            ),
            OrganizationMember(
                org_id=org.id, user_id=operator.id, role="operator"
            ),
            OrganizationMember(org_id=org.id, user_id=agent.id, role="user"),
        ]
    )
    return {"admin": owner, "supervisor": supervisor, "operator": operator, "user": agent}


def test_rbac_authorization_matrix(tmp_path: Path):
    os.environ["DB_URL"] = f"sqlite:///{tmp_path / 'rbac.db'}"
    os.environ["VECTOR_BACKEND"] = "disabled"
    os.environ.pop("EMBED_MODEL_PATH", None)

    from app.application import create_app

    app = create_app()
    database = app.state.container.database
    database.create_schema()

    passwords = AuthService(
        __import__(
            "app.modules.users.repository", fromlist=["UserRepository"]
        ).UserRepository()
    )
    password_hash = passwords.passwords.hash("AdminDemo@2026")
    with database.session_factory() as db:
        org_a = _seed_org(db, "a", password_hash)
        org_b = _seed_org(db, "b", password_hash)
        db.commit()
        # 商家 A 数据
        source_a = tmp_path / "src-a"
        _source(source_a)
        RetailService().import_baskets(db, org_a["admin"].id, source_a)
        # 商家 B 数据 + 一个方案（用于跨组织 404）
        source_b = tmp_path / "src-b"
        _source(source_b)
        RetailService().import_baskets(db, org_b["admin"].id, source_b)
        rule_b = db.scalar(
            select(
                __import__(
                    "app.modules.commerce.models", fromlist=["AssociationRule"]
                ).AssociationRule.id
            ).where(
                __import__(
                    "app.modules.commerce.models", fromlist=["AssociationRule"]
                ).AssociationRule.owner_id
                == org_b["admin"].id
            )
        )
        campaign_b = RetailService().create_campaign(
            db, org_b["admin"].id, rule_b
        )
        # 空闲规则：种子方案占用 top3，矩阵创建用剩余规则（避免防重复 400）
        from app.modules.commerce.models import (
            AssociationRule,
            Campaign as CampaignModel,
        )

        _occupied = set(
            db.scalars(
                select(CampaignModel.rule_id).where(
                    CampaignModel.owner_id == org_a["admin"].id,
                    CampaignModel.status.in_(["draft", "confirmed"]),
                )
            ).all()
        )
        free_rule_ids = [
            rid
            for rid in db.scalars(
                select(AssociationRule.id).where(
                    AssociationRule.owner_id == org_a["admin"].id
                )
            ).all()
            if rid not in _occupied
        ]
        # 商家 A 一条工单（用于 replies 200 分支）
        from app.modules.support.models import SupportCase

        case_a = SupportCase(
            owner_id=org_a["admin"].id,
            case_key="rbac-case-a",
            customer_name="顾客A",
            subject="配送超时",
            status="pending",
            priority="high",
        )
        db.add(case_a)
        # 第二个 case：admin resolve 矩阵行使用（同 case 只能有一个进行中的升级单）
        case_a2 = SupportCase(
            owner_id=org_a["admin"].id,
            case_key="rbac-case-a2",
            customer_name="顾客A2",
            subject="订单漏送",
            status="pending",
            priority="medium",
        )
        db.add(case_a2)
        db.commit()
        case_a_id = case_a.id
        case_a2_id = case_a2.id
        campaign_b_id = campaign_b.id

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                tokens = {}
                for role in ("admin", "supervisor", "operator", "user"):
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={
                            "username": f"a-{role}",
                            "password": "AdminDemo@2026",
                        },
                    )
                    assert resp.status_code == 200, resp.text
                    tokens[role] = {
                        "Authorization": f"Bearer {resp.json()['data']['access_token']}"
                    }

                # 矩阵期望：role -> {api: 200/403}
                matrix = {
                    "user": {
                        "GET /support/cases": 200,
                        # ¹ replies 打在已升级工单上：风险策略下沉后，升级工单
                        # 仅主管可发送对客回复（客服角色 403）
                        "POST replies": 403,
                        "GET /support/escalations": 403,
                        "POST escalation resolve": 403,
                        "GET /retail/overview": 403,
                        "POST /retail/campaigns": 403,
                        "campaign confirm": 403,
                        "campaign publish": 403,
                        "GET /knowledge-bases": 403,
                        "PATCH /rag/settings": 403,
                        "GET /users": 403,
                    },
                    "supervisor": {
                        "GET /support/cases": 200,
                        "POST replies": 200,
                        "GET /support/escalations": 200,
                        "POST escalation resolve": 200,
                        "GET /retail/overview": 403,
                        "POST /retail/campaigns": 403,
                        "campaign confirm": 403,
                        "campaign publish": 403,
                        "GET /knowledge-bases": 403,
                        "PATCH /rag/settings": 403,
                        "GET /users": 403,
                    },
                    "operator": {
                        "GET /support/cases": 403,
                        "POST replies": 403,
                        "GET /support/escalations": 403,
                        "POST escalation resolve": 403,
                        "GET /retail/overview": 200,
                        "POST /retail/campaigns": 200,
                        "campaign confirm": 200,
                        "campaign publish": 403,
                        "GET /knowledge-bases": 403,
                        "PATCH /rag/settings": 403,
                        "GET /users": 403,
                    },
                    "admin": {
                        "GET /support/cases": 200,
                        "POST replies": 200,
                        "GET /support/escalations": 200,
                        "POST escalation resolve": 200,
                        "GET /retail/overview": 200,
                        "POST /retail/campaigns": 200,
                        "campaign confirm": 200,
                        "campaign publish": 200,
                        "GET /knowledge-bases": 200,
                        "PATCH /rag/settings": 200,
                        "GET /users": 200,
                    },
                }

                # 准备共享资源
                settings_version = (
                    await client.get("/api/v1/rag/settings", headers=tokens["admin"])
                ).json()["data"]["version"]
                rules = (
                    await client.get("/api/v1/retail/overview", headers=tokens["admin"])
                ).json()["data"]["rules"]
                # 空闲规则创建方案（top3 被种子方案占用，防重复校验只拦 draft/confirmed）
                campaign_a = (
                    await client.post(
                        "/api/v1/retail/campaigns",
                        headers=tokens["admin"],
                        json={"ruleId": free_rule_ids.pop(0)},
                    )
                ).json()["data"]
                campaign_a_id = campaign_a["id"]
                admin_campaign = (
                    await client.post(
                        "/api/v1/retail/campaigns",
                        headers=tokens["admin"],
                        json={"ruleId": free_rule_ids.pop(0)},
                    )
                ).json()["data"]
                admin_campaign_id = admin_campaign["id"]
                # 升级单（商家 A）两个：主管与 admin 各自 resolve（状态机不允许重复解决）
                escalated = await client.post(
                    f"/api/v1/support/cases/{case_a_id}/escalations",
                    headers=tokens["admin"],
                    json={
                        "category": "compensation_request",
                        "reason": "顾客要求补偿",
                        "riskLevel": "medium",
                    },
                )
                escalation_id = escalated.json()["data"]["id"]
                await client.post(
                    f"/api/v1/support/escalations/{escalation_id}/accept",
                    headers=tokens["admin"],
                )
                escalated_admin = await client.post(
                    f"/api/v1/support/cases/{case_a2_id}/escalations",
                    headers=tokens["admin"],
                    json={
                        "category": "customer_complaint",
                        "reason": "顾客要求复核退款",
                        "riskLevel": "high",
                    },
                )
                assert escalated_admin.status_code == 200, escalated_admin.text
                escalation_admin_id = escalated_admin.json()["data"]["id"]
                await client.post(
                    f"/api/v1/support/escalations/{escalation_admin_id}/accept",
                    headers=tokens["admin"],
                )

                def call(role, api):
                    role_headers = tokens[role]
                    if api == "GET /support/cases":
                        return client.get("/api/v1/support/cases", headers=role_headers)
                    if api == "POST replies":
                        return client.post(
                            f"/api/v1/support/cases/{case_a_id}/replies",
                            headers=role_headers,
                            json={"content": "已联系骑手核实"},
                        )
                    if api == "GET /support/escalations":
                        return client.get(
                            "/api/v1/support/escalations", headers=role_headers
                        )
                    if api == "POST escalation resolve":
                        target_esc = (
                            escalation_admin_id if role == "admin" else escalation_id
                        )
                        return client.post(
                            f"/api/v1/support/escalations/{target_esc}/resolve",
                            headers=role_headers,
                            json={"resolution": "approved_refund", "resolutionNote": "已核实"},
                        )
                    if api == "GET /retail/overview":
                        return client.get("/api/v1/retail/overview", headers=role_headers)
                    if api == "POST /retail/campaigns":
                        # operator/admin 各用一条剩余空闲规则（互不冲突）
                        rule_index = 0 if role == "operator" else 1
                        return client.post(
                            "/api/v1/retail/campaigns",
                            headers=role_headers,
                            json={"ruleId": free_rule_ids[rule_index]},
                        )
                    if api == "campaign confirm":
                        # operator 确认 admin 创建的方案；admin 确认自己的方案
                        target = (
                            campaign_a_id if role == "operator" else admin_campaign_id
                        )
                        return client.post(
                            f"/api/v1/retail/campaigns/{target}/transition",
                            headers=role_headers,
                            json={"action": "confirm", "expectedVersion": 1},
                        )
                    if api == "campaign publish":
                        return client.post(
                            f"/api/v1/retail/campaigns/{admin_campaign_id}/transition",
                            headers=role_headers,
                            json={"action": "publish", "expectedVersion": 2},
                        )
                    if api == "GET /knowledge-bases":
                        return client.get("/api/v1/knowledge-bases", headers=role_headers)
                    if api == "PATCH /rag/settings":
                        return client.patch(
                            "/api/v1/rag/settings",
                            headers=role_headers,
                            json={
                                "expectedVersion": settings_version,
                                "changes": [
                                    {"key": "retrieval_candidate_limit", "value": 21}
                                ],
                                "resetKeys": [],
                            },
                        )
                    if api == "GET /users":
                        return client.get("/api/v1/users", headers=role_headers)
                    raise AssertionError(api)

                failures = []
                for role, expectations in matrix.items():
                    for api, expected in expectations.items():
                        resp = await call(role, api)
                        if resp.status_code != expected:
                            failures.append(
                                f"{role} -> {api}: 期望 {expected} 实际 {resp.status_code}"
                            )
                assert not failures, "\n".join(failures)

                # 跨组织：商家 A 的运营访问商家 B 的方案 → 404（不暴露存在性）
                resp = await client.get(
                    f"/api/v1/retail/campaigns/{campaign_b_id}",
                    headers=tokens["operator"],
                )
                assert resp.status_code == 404, resp.text
                resp = await client.post(
                    f"/api/v1/retail/campaigns/{campaign_b_id}/transition",
                    headers=tokens["operator"],
                    json={"action": "confirm", "expectedVersion": 1},
                )
                assert resp.status_code == 404, resp.text
                # 商家 B 的 admin 自己可以访问（对照）
                resp = await client.post(
                    "/api/v1/auth/login",
                    json={"username": "b-admin", "password": "AdminDemo@2026"},
                )
                assert resp.status_code == 200, resp.text
                tokens_b_admin = {
                    "Authorization": f"Bearer {resp.json()['data']['access_token']}"
                }
                resp = await client.get(
                    f"/api/v1/retail/campaigns/{campaign_b_id}",
                    headers=tokens_b_admin,
                )
                assert resp.status_code == 200, resp.text

    asyncio.run(scenario())
    database.engine.dispose()
