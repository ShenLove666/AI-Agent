from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, timedelta

import httpx

from app.framework.config import Settings
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.provenance.models import DataSource
from app.modules.support.models import (
    KnowledgeRelease,
    KnowledgeReleaseDocument,
    SupportCase,
    SupportMessage,
)


def test_support_case_api_contract(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/v1/auth/register", json={"username": "agent", "password": "password123"})
                login = await client.post("/api/v1/auth/login", json={"username": "agent", "password": "password123"})
                token = login.json()["data"]["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                with app.state.container.database.session_factory() as db:
                    # 契约测试使用管理员账号，与域隔离权限测试分开
                    from app.modules.users.models import User

                    account = db.query(User).filter_by(username="agent").one()
                    account.role = "admin"
                    db.commit()
                with app.state.container.database.session_factory() as db:
                    case = SupportCase(owner_id=1, case_key="api-1", customer_name="顾客", subject="配送超时", status="pending", priority="high")
                    db.add(case); db.flush()
                    source = DataSource(
                        owner_id=1, dataset_key="contract-source", version="v1", title="契约来源",
                        source_kind="local", source_uri="project://fixture", publisher="测试",
                        license="测试用途", retrieved_at=date.today(), encoding="utf-8",
                        schema_json="{}", limitations_json='["仅测试"]', transform_version="v1",
                        manifest_sha256="d" * 64, is_demo=True,
                    )
                    db.add(source); db.flush()
                    db.add(SupportMessage(case_id=case.id, role="customer", content="订单迟到了")); db.commit()
                    case_id = case.id
                    source_id = source.id
                listed = await client.get("/api/v1/support/cases?status=pending&priority=high", headers=headers)
                assert listed.status_code == 200
                assert listed.json()["data"][0]["caseKey"] == "api-1"
                assigned = await client.post(f"/api/v1/support/cases/{case_id}/assign", headers=headers, json={"assigneeId": 1, "expectedVersion": 1})
                assert assigned.status_code == 200
                assert assigned.json()["data"]["status"] == "in_progress"
                replied = await client.post(f"/api/v1/support/cases/{case_id}/replies", headers=headers, json={"content": "已联系骑手核实"})
                assert replied.status_code == 200
                assert replied.json()["data"]["messages"][-1]["sentToCustomer"] is True
                metrics = await client.get("/api/v1/support/metrics", headers=headers)
                assert metrics.status_code == 200
                assert metrics.json()["data"]["totalCases"] == 1
                provenance = await client.get(f"/api/v1/support/cases/{case_id}/provenance", headers=headers)
                assert provenance.status_code == 200
                coverage = await client.get("/api/v1/support/coverage", headers=headers)
                assert coverage.status_code == 200
                assert coverage.json()["data"]["totalCases"] == 1
                sources = await client.get("/api/v1/data-sources", headers=headers)
                assert sources.status_code == 200
                assert sources.json()["data"][0]["datasetKey"] == "contract-source"
                quality = await client.get(f"/api/v1/data-sources/{source_id}/quality", headers=headers)
                assert quality.status_code == 200
                assert quality.json()["data"]["manifestSha256"] == "d" * 64

    asyncio.run(scenario())


def test_support_citations_expose_complete_source_metadata(tmp_path):
    async def scenario():
        from app.application import create_app

        app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'citation-api.db'}"))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/v1/auth/register", json={"username": "merchant", "password": "password123"})
                login = await client.post("/api/v1/auth/login", json={"username": "merchant", "password": "password123"})
                headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
                with app.state.container.database.session_factory() as db:
                    # 契约测试使用管理员账号（知识发布/来源属于 knowledge.manage）
                    from app.modules.users.models import User

                    account = db.query(User).filter_by(username="merchant").one()
                    account.role = "admin"
                    db.commit()
                with app.state.container.database.session_factory() as db:
                    base = KnowledgeBase(owner_id=1, name="官方规则"); db.add(base); db.flush()
                    document = KnowledgeDocument(
                        knowledge_base_id=base.id, uploader_id=1, filename="returns.md", file_type="md",
                        storage_path="returns.md", file_size=32, status="indexed", enabled=True,
                        content_origin="public_summary", source_title="七日无理由退货规则摘要",
                        source_url="https://example.gov/returns", source_publisher="国家监管机构",
                        source_retrieved_at=date.today(), next_review_at=date.today() + timedelta(days=90),
                        review_status="current", applicability_json='["网络零售"]',
                        exclusions_json='["鲜活易腐"]', source_usage_note="项目原创摘要",
                        demo_content_sha256=hashlib.sha256(b"returns").hexdigest(),
                    )
                    db.add(document); db.flush()
                    chunk = KnowledgeChunk(knowledge_base_id=base.id, document_id=document.id, position=0, content="七日期间从签收商品的次日开始计算。", enabled=True)
                    db.add(chunk); db.flush()
                    release = KnowledgeRelease(owner_id=1, version="v1", title="正式规则", status="published", processing_status="ready", content_hash="c" * 64, is_active=True)
                    db.add(release); db.flush()
                    db.add(KnowledgeReleaseDocument(release_id=release.id, document_id=document.id, document_hash=document.demo_content_sha256, filename_snapshot=document.filename))
                    case = SupportCase(owner_id=1, case_key="citation-1", customer_name="顾客", subject="退货期限", status="pending", priority="normal")
                    db.add(case); db.flush()
                    db.add(SupportMessage(case_id=case.id, role="customer", content="七天从哪天开始算？")); db.commit()
                    case_id = case.id

                sources = await client.get("/api/v1/support/knowledge/sources", headers=headers)
                assert sources.status_code == 200
                assert sources.json()["data"][0]["publisher"] == "国家监管机构"
                suggestion = await client.post(f"/api/v1/support/cases/{case_id}/suggestions", headers=headers)
                assert suggestion.status_code == 200
                citation = suggestion.json()["data"]["citations"][0]
                assert citation == {
                    **citation,
                    "docId": citation["docId"],
                    "docName": "七日无理由退货规则摘要",
                    "publisher": "国家监管机构",
                    "canonicalUrl": "https://example.gov/returns",
                    "applicability": ["网络零售"],
                    "exclusions": ["鲜活易腐"],
                    "reviewStatus": "current",
                }

    asyncio.run(scenario())
