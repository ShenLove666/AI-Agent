from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.support.service import SupportService
from app.modules.users.models import User


def _seed_passing_run(
    db, owner_id: int, release_id: int, release_version: str
) -> EvaluationRun:
    """构造一条全通过的评测运行（门禁测试用，绕开真实 LLM）。"""
    dataset = EvaluationDataset(owner_id=owner_id, name="门禁集", is_demo=True)
    db.add(dataset)
    db.flush()
    case = EvaluationCase(
        dataset_id=dataset.id,
        case_key="gate-1",
        question="政策问题",
        category="policy",
        difficulty="basic",
        expected_points_json="[]",
        expected_document_keys_json="[]",
        should_refuse=False,
    )
    db.add(case)
    db.flush()
    run = EvaluationRun(
        owner_id=owner_id,
        dataset_id=dataset.id,
        status="completed",
        config_snapshot_json=json.dumps(
            {
                "knowledgeReleaseId": release_id,
                "knowledgeVersion": release_version,
            },
            ensure_ascii=False,
        ),
    )
    db.add(run)
    db.flush()
    db.add(
        EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            answer="已按政策答复。",
            expected_point_score=100,
            citation_correct=True,
            refusal_correct=True,
            latency_ms=200,
            evidence_json=json.dumps(
                {"metrics": {"total_score": 100, "evidence_recall": 100}},
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    return run


def test_release_membership_is_frozen_and_activation_requires_approval(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'release.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username="merchant", password_hash="hash", role="admin")
        outsider = User(username="other", password_hash="hash")
        db.add_all([owner, outsider]); db.flush()
        base = KnowledgeBase(owner_id=owner.id, name="客服政策"); db.add(base); db.flush()
        document = KnowledgeDocument(knowledge_base_id=base.id, uploader_id=owner.id, filename="refund-v1.md", file_type="md", storage_path="refund-v1.md", file_size=20, status="indexed", enabled=True, demo_content_sha256="a" * 64)
        db.add(document); db.flush()
        db.add(KnowledgeChunk(knowledge_base_id=base.id, document_id=document.id, position=0, content="生鲜破损经审核后原路退款", enabled=True)); db.commit()
        service = SupportService()
        draft = service.create_release(db, owner.id, owner.id, "v1", "售后政策 v1", [document.id])
        document.filename = "mutated.md"; db.commit()
        published = service.publish_release(db, owner.id, draft["id"], owner.id)
        # 未经过评测门禁批准 → 裸激活必须被拒绝
        with pytest.raises(AppError) as blocked:
            service.activate_release(db, owner.id, published["id"])
        assert blocked.value.code == "KNOWLEDGE_RELEASE_NOT_APPROVED"
        assert blocked.value.status_code == 409
        # 批准（唯一激活入口）后，激活允许且成员快照保持冻结
        run = _seed_passing_run(db, owner.id, published["id"], published["version"])
        approved = service.decide_release(
            db, owner.id, owner.id, run.id, published["id"], "approved"
        )
        assert approved["decision"] == "approved" and approved["gate"]["passed"] is True
        active = service.activate_release(db, owner.id, published["id"])
        assert active["isActive"] is True
        assert active["documents"][0]["filename"] == "refund-v1.md"
        try:
            service.activate_release(db, outsider.id, active["id"])
        except AppError as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("cross-owner release must not be visible")


def test_activation_rejects_content_hash_drift(tmp_path):
    """批准后内容哈希漂移（文档变更）→ 激活被拒，必须重新评测批准。"""
    database = Database(f"sqlite:///{tmp_path / 'drift.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username="drift-owner", password_hash="hash", role="admin")
        db.add(owner); db.flush()
        base = KnowledgeBase(owner_id=owner.id, name="政策库"); db.add(base); db.flush()
        document = KnowledgeDocument(
            knowledge_base_id=base.id, uploader_id=owner.id,
            filename="drift-v1.md", file_type="md", storage_path="drift-v1.md",
            file_size=10, status="indexed", enabled=True,
        )
        db.add(document); db.flush()
        db.add(
            KnowledgeChunk(
                knowledge_base_id=base.id, document_id=document.id,
                position=0, content="政策内容", enabled=True,
            )
        )
        db.commit()
        service = SupportService()
        draft = service.create_release(
            db, owner.id, owner.id, "v2", "政策 v2", [document.id]
        )
        published = service.publish_release(db, owner.id, draft["id"], owner.id)
        run = _seed_passing_run(db, owner.id, published["id"], published["version"])
        service.decide_release(db, owner.id, owner.id, run.id, published["id"], "approved")
        # 模拟批准后内容发生变化（哈希漂移）
        from app.modules.support.models import KnowledgeRelease

        release = db.scalar(
            __import__("sqlalchemy").select(KnowledgeRelease).where(
                KnowledgeRelease.id == published["id"]
            )
        )
        release.content_hash = "drifted-hash"
        db.commit()
        with pytest.raises(AppError) as blocked:
            service.activate_release(db, owner.id, published["id"])
        assert blocked.value.code == "KNOWLEDGE_RELEASE_CONTENT_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "expected_bucket"),
    [
        ("missing_applicability", "unattributed"),
        ("review_due", "stale"),
        ("superseded", "stale"),
        ("provenance_conflict", "conflicts"),
    ],
)
def test_publication_blocks_untrusted_or_stale_sources(tmp_path, mutation, expected_bucket):
    database = Database(f"sqlite:///{tmp_path / f'{mutation}.db'}")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as db:
        owner = User(username=f"owner-{mutation}", password_hash="hash", role="admin")
        db.add(owner); db.flush()
        base = KnowledgeBase(owner_id=owner.id, name="可信知识"); db.add(base); db.flush()
        document = KnowledgeDocument(
            knowledge_base_id=base.id,
            uploader_id=owner.id,
            filename="policy.md",
            file_type="md",
            storage_path="policy.md",
            file_size=20,
            status="indexed",
            enabled=True,
            demo_content_sha256="b" * 64,
            content_origin="public_summary",
            source_title="官方政策摘要",
            source_url="https://example.gov/policy",
            source_publisher="权威机构",
            source_retrieved_at=date.today(),
            next_review_at=date.today() + timedelta(days=30),
            review_status="current",
            applicability_json='["中国大陆网络零售"]',
            source_usage_note="项目原创摘要，以官方原文为准。",
        )
        if mutation == "missing_applicability":
            document.applicability_json = "[]"
        elif mutation == "review_due":
            document.next_review_at = date.today() - timedelta(days=1)
        else:
            if mutation == "superseded":
                document.review_status = "superseded"
            else:
                document.content_origin = "synthetic"
        db.add(document); db.flush()
        db.add(KnowledgeChunk(knowledge_base_id=base.id, document_id=document.id, position=0, content="有效政策证据", enabled=True)); db.commit()

        service = SupportService()
        draft = service.create_release(db, owner.id, owner.id, f"v-{mutation}", "可信知识版本", [document.id])
        with pytest.raises(AppError) as caught:
            service.publish_release(db, owner.id, draft["id"], owner.id)
        assert caught.value.code == "KNOWLEDGE_PROVENANCE_INVALID"
        assert document.filename in caught.value.details[expected_bucket]
