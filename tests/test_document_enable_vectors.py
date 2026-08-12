"""禁用/启用文档的向量同步：禁用删除向量（防向量通道泄露），启用从 chunk 重建。"""

from __future__ import annotations

from pathlib import Path

from app.framework.database import Base, Database
from app.modules.knowledge.service import KnowledgeService


class _FakeVectorIndexer:
    """记录向量删除/索引调用的假索引器（VectorIndexer 鸭子类型）。"""

    def __init__(self) -> None:
        self.deleted: list[int] = []
        self.indexed: list[dict] = []

    @property
    def store(self):
        return self

    async def delete_document(self, document_id: int) -> None:
        self.deleted.append(document_id)

    async def index(self, **kwargs) -> None:
        self.indexed.append(kwargs)


def test_disable_deletes_vectors_and_enable_rebuilds(tmp_path: Path):
    from app.modules.knowledge.models import (
        KnowledgeBase,
        KnowledgeChunk,
        KnowledgeDocument,
    )
    from app.modules.users.models import User

    database = Database(f"sqlite:///{tmp_path / 'vectors.db'}")
    Base.metadata.create_all(database.engine)
    fake = _FakeVectorIndexer()
    service = KnowledgeService(vector_indexer=fake)
    with database.session_factory() as db:
        user = User(username="kuser", password_hash="x", role="admin")
        db.add(user)
        db.flush()
        base = KnowledgeBase(owner_id=user.id, name="kb")
        db.add(base)
        db.flush()
        doc = KnowledgeDocument(
            knowledge_base_id=base.id,
            uploader_id=user.id,
            filename="p.md",
            file_type="md",
            storage_path="/tmp/p.md",
            status="indexed",
            vector_indexed=True,
        )
        db.add(doc)
        db.flush()
        chunk = KnowledgeChunk(
            knowledge_base_id=base.id,
            document_id=doc.id,
            position=0,
            content="退货政策内容",
        )
        db.add(chunk)
        db.flush()
        chunk_id = chunk.id
        db.commit()

        # 禁用：向量同步删除，避免向量通道仍检索到已禁用文档
        service.set_document_enabled(db, doc.id, False)
        db.refresh(doc)
        assert doc.status == "disabled"
        assert fake.deleted == [doc.id]
        assert doc.vector_indexed is False

        # 重新启用：从存量 chunk 重建向量，owner 归属知识库所属商家
        service.set_document_enabled(db, doc.id, True)
        db.refresh(doc)
        assert doc.status == "indexed"
        assert doc.vector_indexed is True
        assert len(fake.indexed) == 1
        rebuilt = fake.indexed[0]
        assert rebuilt["document_id"] == doc.id
        assert rebuilt["owner_id"] == user.id
        assert [item[0] for item in rebuilt["chunks"]] == [chunk_id]


def test_missing_document_raises_404(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'missing.db'}")
    Base.metadata.create_all(database.engine)
    service = KnowledgeService(vector_indexer=_FakeVectorIndexer())
    with database.session_factory() as db:
        try:
            service.set_document_enabled(db, 999, False)
        except Exception as exc:  # noqa: BLE001
            assert type(exc).__name__ == "AppError"
            assert getattr(exc, "code", None) == "DOCUMENT_NOT_FOUND"
        else:
            raise AssertionError("缺少文档应抛出 DOCUMENT_NOT_FOUND")
