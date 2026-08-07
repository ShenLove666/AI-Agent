from __future__ import annotations

from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.support.service import SupportService
from app.modules.users.models import User


def test_release_membership_is_frozen_and_activation_is_explicit(tmp_path):
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
        active = service.activate_release(db, owner.id, published["id"])
        assert active["isActive"] is True
        assert active["documents"][0]["filename"] == "refund-v1.md"
        try:
            service.activate_release(db, outsider.id, active["id"])
        except AppError as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("cross-owner release must not be visible")
