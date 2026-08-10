"""知识库遗留路由（knowledge_mutations / knowledge_fixes）data_owner 统一回归测试。

覆盖：
1. knowledge_mutations DELETE /knowledge-bases/{base}/documents/{doc}：
   归属校验按 resolve_owner 的商家数据 owner，跨商家一律 404
   （KNOWLEDGE_BASE_NOT_FOUND，与 require_owned_base 语义一致）；本人（组织
   成员视角为组织数据）删除成功 204。
2. knowledge_fixes 单数 /knowledge-base 遗留路由：owner 过滤/校验统一按
   data_owner_id（组织成员 → 组织 owner），不再按 user.id / admin 旁路；
   跨商家 403 FORBIDDEN，列表只见自己 data_owner 名下的 base。
3. chunk 遗留路由（knowledge_chunk_fixes 依赖同套 _document/_chunk 校验）：
   跨商家 403。
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import httpx
from sqlalchemy import select

from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.users.access import resolve_owner
from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.users.repository import UserRepository


def _seed_org(db, *, owner: User, member: User) -> Organization:
    org = Organization(name="商家组织", owner_user_id=owner.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(org_id=org.id, user_id=member.id, role="operator"))
    # 组织 owner 同时也是成员（与 demo seed 行为一致）
    db.add(OrganizationMember(org_id=org.id, user_id=owner.id, role="owner"))
    db.commit()
    return org


def test_legacy_routes_use_data_owner():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            os.environ["DB_URL"] = f"sqlite:///{directory}/legacy-owner.db"
            os.environ["VECTOR_BACKEND"] = "disabled"
            from app.application import create_app

            app = create_app()
            transport = httpx.ASGITransport(app=app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    for username in ("merchant-a", "member-b", "merchant-c"):
                        await client.post(
                            "/api/v1/auth/register",
                            json={"username": username, "password": "password123"},
                        )
                    # A=商家 owner；B=组织成员（admin 过 knowledge.manage 门禁，
                    # 数据域解析为组织 owner A）；C=无关商家（admin，无组织归属）。
                    with app.state.container.database.session_factory() as db:
                        repo = UserRepository()
                        owner_a = repo.get_by_username(db, "merchant-a")
                        member_b = repo.get_by_username(db, "member-b")
                        foreign_c = repo.get_by_username(db, "merchant-c")
                        owner_a.role = "user"
                        member_b.role = "admin"
                        foreign_c.role = "admin"
                        db.flush()
                        _seed_org(db, owner=owner_a, member=member_b)
                        db.commit()
                        assert resolve_owner(db, member_b) == owner_a.id
                        assert resolve_owner(db, foreign_c) == foreign_c.id

                    async def login(username: str) -> dict:
                        response = await client.post(
                            "/api/v1/auth/login",
                            json={"username": username, "password": "password123"},
                        )
                        return {
                            "Authorization": (
                                "Bearer "
                                f"{response.json()['data']['access_token']}"
                            )
                        }

                    headers_b = await login("member-b")
                    headers_c = await login("merchant-c")

                    # B 经新路由创建 base → 归属组织 owner A
                    created = await client.post(
                        "/api/v1/knowledge-bases",
                        json={"name": "A 商家知识库"},
                        headers=headers_b,
                    )
                    assert created.status_code == 201
                    base_id = created.json()["data"]["id"]
                    with app.state.container.database.session_factory() as db:
                        assert db.get(KnowledgeBase, base_id).owner_id == db.scalar(
                            select(User.id).where(User.username == "merchant-a")
                        )
                        document = KnowledgeDocument(
                            knowledge_base_id=base_id,
                            uploader_id=db.scalar(
                                select(User.id).where(User.username == "member-b")
                            ),
                            filename="退货政策.txt",
                            file_type="txt",
                            storage_path=f"{directory}/policy.txt",
                            file_size=1,
                            status="indexed",
                        )
                        db.add(document)
                        db.commit()
                        document_id = document.id

                    # 1) knowledge_mutations DELETE：跨商家被拒（404 语义与
                    #    require_owned_base 一致，不暴露他人知识库存在性）
                    forbidden = await client.delete(
                        f"/api/v1/knowledge-bases/{base_id}/documents/{document_id}",
                        headers=headers_c,
                    )
                    assert forbidden.status_code == 404
                    assert forbidden.json()["error"]["code"] == (
                        "KNOWLEDGE_BASE_NOT_FOUND"
                    )

                    # 2) knowledge_fixes 遗留 GET：跨商家 403 FORBIDDEN
                    forbidden_list = await client.get(
                        f"/api/v1/knowledge-base/{base_id}/docs",
                        headers=headers_c,
                    )
                    assert forbidden_list.status_code == 403
                    assert forbidden_list.json()["error"]["code"] == "FORBIDDEN"

                    # 3) knowledge_fixes 遗留列表：B 只见自己 data_owner 名下 base
                    listed = await client.get(
                        "/api/v1/knowledge-base?current=1&size=10", headers=headers_b
                    )
                    names = [
                        record["name"] for record in listed.json()["data"]["records"]
                    ]
                    assert "A 商家知识库" in names

                    # 4) knowledge_chunk_fixes 依赖的同套校验：C 无法访问
                    #    B 组织 base 的 chunk 列表（403）
                    forbidden_chunks = await client.get(
                        f"/api/v1/knowledge-base/docs/{document_id}/chunks",
                        headers=headers_c,
                    )
                    assert forbidden_chunks.status_code == 403

                    # 5) B 删除自己的文档（组织数据域）→ 204
                    deleted = await client.delete(
                        f"/api/v1/knowledge-bases/{base_id}/documents/{document_id}",
                        headers=headers_b,
                    )
                    assert deleted.status_code == 204
                    with app.state.container.database.session_factory() as db:
                        assert db.get(KnowledgeDocument, document_id) is None

    asyncio.run(scenario())
