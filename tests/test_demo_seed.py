from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.framework.database import Base, Database
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.users.models import User


@pytest.fixture
def db(tmp_path) -> Session:
    database = Database(f"sqlite:///{tmp_path / 'demo-metadata.db'}")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
        database.engine.dispose()


@pytest.fixture
def user(db: Session) -> User:
    item = User(username="owner", password_hash="hash")
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def knowledge_base(db: Session, user: User) -> KnowledgeBase:
    item = KnowledgeBase(owner_id=user.id, name="demo")
    db.add(item)
    db.flush()
    return item


def test_regular_user_and_upload_are_not_demo_or_public_by_default(db: Session):
    user = User(username="owner", password_hash="hash")
    db.add(user)
    db.flush()

    assert user.is_demo is False


def test_public_summary_keeps_provenance(
    db: Session, knowledge_base: KnowledgeBase, user: User
):
    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        uploader_id=user.id,
        filename="return-summary.md",
        file_type="md",
        storage_path="resources/demo/documents/seven-day-return-summary.md",
        content_origin="public_summary",
        source_url=(
            "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
            "art_26ca8fe29e184edd899fa0a7a060d935.html"
        ),
        source_publisher="国家市场监督管理总局",
        source_retrieved_at=date(2026, 8, 7),
        source_usage_note="原创摘要，仅用于本地演示；原文以来源页面为准。",
    )
    db.add(document)
    db.commit()

    assert document.content_origin == "public_summary"


def test_document_rejects_unknown_content_origin(
    knowledge_base: KnowledgeBase, user: User
):
    with pytest.raises(ValueError, match="content_origin must be one of"):
        KnowledgeDocument(
            knowledge_base_id=knowledge_base.id,
            uploader_id=user.id,
            filename="unknown.txt",
            file_type="txt",
            storage_path="unknown.txt",
            content_origin="partner_upload",
        )
