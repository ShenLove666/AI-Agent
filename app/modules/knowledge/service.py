from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.modules.vector.indexer import VectorIndexer


_POLICY_TERMS = ("政策", "规则", "退货", "退款", "售后")
_RECOMMENDATION_TERMS = ("指南", "推荐", "搭配")
_PRODUCT_TERMS = ("商品", "说明")


def infer_source_kind(*names: str) -> str:
    """按文件名/知识库名做初始 source_kind 推断（简单规则）。

    含 政策/规则/退货/退款/售后 → policy；
    含 指南/推荐/搭配 → recommendation_guide；
    含 商品/说明 → product_knowledge；
    其余 → general。
    """
    text = " ".join(name or "" for name in names)
    if any(term in text for term in _POLICY_TERMS):
        return "policy"
    if any(term in text for term in _RECOMMENDATION_TERMS):
        return "recommendation_guide"
    if any(term in text for term in _PRODUCT_TERMS):
        return "product_knowledge"
    return "general"


class DocumentParser:
    def parse(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if suffix == ".docx":
            from docx import Document

            return "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs)
        raise AppError("UNSUPPORTED_DOCUMENT", f"暂不支持 {suffix or '未知'} 文件", 400)


class TextChunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, text: str) -> list[str]:
        normalized = re.sub(r"\r\n?", "\n", text).strip()
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.chunk_size, len(normalized))
            if end < len(normalized):
                boundary = max(normalized.rfind(mark, start, end) for mark in ("\n", "。", "！", "？"))
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1
            chunks.append(normalized[start:end].strip())
            if end >= len(normalized):
                break
            start = max(start + 1, end - self.overlap)
        return [chunk for chunk in chunks if chunk]


class KnowledgeService:
    def __init__(
        self,
        parser: DocumentParser | None = None,
        chunker: TextChunker | None = None,
        vector_indexer: VectorIndexer | None = None,
    ):
        self.parser = parser or DocumentParser()
        self.chunker = chunker or TextChunker()
        self.vector_indexer = vector_indexer

    def create_base(
        self, db: Session, *, owner_id: int, name: str, description: str | None = None
    ) -> KnowledgeBase:
        """创建知识库。

        owner_id 是「商家数据 owner」（resolve_owner 结果），与操作者
        （actor）分离：组织成员（operator）创建的知识库归属组织 owner，
        uploader 类字段才记录操作者本人。
        """
        item = KnowledgeBase(owner_id=owner_id, name=name, description=description)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def list_bases(self, db: Session, owner_id: int) -> list[KnowledgeBase]:
        """列出 owner_id（商家数据 owner）名下的知识库。"""
        return list(
            db.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.owner_id == owner_id)
                .order_by(KnowledgeBase.created_at.desc())
            )
        )

    def require_owned_base(self, db: Session, base_id: int, owner_id: int) -> KnowledgeBase:
        """归属校验：base 必须属于 owner_id（商家数据 owner，resolve_owner 结果）。

        跨商家 base 一律抛 404（KNOWLEDGE_BASE_NOT_FOUND），语义与
        Chat 侧 _assert_knowledge_base_access 的 403 一致：不暴露他人知识库存在性。
        """
        item = db.get(KnowledgeBase, base_id)
        if not item or item.owner_id != owner_id:
            raise AppError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", 404)
        return item

    def create_document(
        self,
        db: Session,
        *,
        base_id: int,
        uploader_id: int,
        owner_id: int,
        filename: str,
        storage_path: str,
        file_size: int,
    ) -> KnowledgeDocument:
        """创建文档记录（不解析/不摄取，状态 pending）。

        owner_id 是「商家数据 owner」（resolve_owner 结果），仅用于归属校验
        （require_owned_base）；uploader_id 记录实际操作者（actor），两者
        可不同：组织成员（operator）上传文档时 owner=组织 owner、
        uploader=成员自身。
        """
        self.require_owned_base(db, base_id, owner_id)
        item = KnowledgeDocument(
            knowledge_base_id=base_id,
            uploader_id=uploader_id,
            filename=filename,
            file_type=Path(filename).suffix.lower().lstrip("."),
            storage_path=storage_path,
            file_size=file_size,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def ingest_document(self, db: Session, document_id: int) -> KnowledgeDocument:
        document = db.get(KnowledgeDocument, document_id)
        if not document:
            raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", 404)
        document.status = "processing"
        document.error_message = None
        db.commit()
        try:
            chunks = self.chunker.split(self.parser.parse(Path(document.storage_path)))
            if not chunks:
                raise ValueError("文档没有可索引的文本")
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
            chunk_rows = [
                KnowledgeChunk(
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    position=position,
                    content=content,
                )
                for position, content in enumerate(chunks)
            ]
            db.add_all(chunk_rows)
            db.flush()
            vector_chunks = [
                (chunk.id, chunk.position, chunk.content) for chunk in chunk_rows
            ]
            base = db.get(KnowledgeBase, document.knowledge_base_id)
            document.source_kind = infer_source_kind(
                document.filename, base.name if base is not None else None
            )
            db.commit()

            # parse + chunk 写库成功 → keyword 检索立即可用：
            # status=indexed 且 vector_indexed=False（即使后续向量索引失败也保持可用）。
            document.status = "indexed"
            document.vector_indexed = False
            document.error_message = None
            db.commit()

            if self.vector_indexer is not None:
                try:
                    # Remove every previous generation before inserting the new DB-backed chunk IDs.
                    # This prevents shorter re-chunks from leaving searchable stale vectors.
                    asyncio.run(self.vector_indexer.store.delete_document(document.id))
                    # 向量按「文档所属 base 的商家数据 owner」归档（与上传者
                    # uploader_id 无关）：组织成员上传的文档向量归属组织 owner，
                    # 保证 Chat 按 data_owner_id 检索时能命中。
                    asyncio.run(
                        self.vector_indexer.index(
                            owner_id=(
                                base.owner_id if base is not None else document.uploader_id
                            ),
                            knowledge_base_id=document.knowledge_base_id,
                            document_id=document.id,
                            source=document.filename,
                            chunks=vector_chunks,
                        )
                    )
                    document.vector_indexed = True
                    document.error_message = None
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    # 向量索引失败 ≠ 文档不可用：降级为关键词检索，status 保持 indexed。
                    # 尽力清理本次写入的残留向量（清理失败不影响降级结果）。
                    db.rollback()
                    document = db.get(KnowledgeDocument, document_id)
                    try:
                        asyncio.run(
                            self.vector_indexer.store.delete_document(document.id)
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    document.vector_indexed = False
                    document.status = "indexed"
                    document.error_message = (
                        f"向量索引失败，当前已降级使用关键词检索：{exc}"
                    )
                    db.commit()
        except Exception as exc:
            # 只有 parse 失败/文档为空/chunk 为空/DB 写入失败才置 failed
            db.rollback()
            document = db.get(KnowledgeDocument, document_id)
            document.status = "failed"
            document.error_message = str(exc)
            db.commit()
        db.refresh(document)
        return document

    def list_documents(
        self, db: Session, base_id: int, owner_id: int
    ) -> list[KnowledgeDocument]:
        """列出 base 的文档；base 必须属于 owner_id（商家数据 owner）。"""
        self.require_owned_base(db, base_id, owner_id)
        return list(
            db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.knowledge_base_id == base_id)
                .order_by(KnowledgeDocument.created_at.desc())
            )
        )
