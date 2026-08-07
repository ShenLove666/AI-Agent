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
        self, db: Session, owner_id: int, name: str, description: str | None = None
    ) -> KnowledgeBase:
        item = KnowledgeBase(owner_id=owner_id, name=name, description=description)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def list_bases(self, db: Session, owner_id: int) -> list[KnowledgeBase]:
        return list(
            db.scalars(
                select(KnowledgeBase)
                .where(KnowledgeBase.owner_id == owner_id)
                .order_by(KnowledgeBase.created_at.desc())
            )
        )

    def require_owned_base(self, db: Session, base_id: int, owner_id: int) -> KnowledgeBase:
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
        filename: str,
        storage_path: str,
        file_size: int,
    ) -> KnowledgeDocument:
        self.require_owned_base(db, base_id, uploader_id)
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
            db.commit()

            if self.vector_indexer is not None:
                # Remove every previous generation before inserting the new DB-backed chunk IDs.
                # This prevents shorter re-chunks from leaving searchable stale vectors.
                asyncio.run(self.vector_indexer.store.delete_document(document.id))
                asyncio.run(
                    self.vector_indexer.index(
                        owner_id=document.uploader_id,
                        knowledge_base_id=document.knowledge_base_id,
                        document_id=document.id,
                        source=document.filename,
                        chunks=vector_chunks,
                    )
                )
            document.status = "indexed"
            document.error_message = None
            db.commit()
        except Exception as exc:
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
        self.require_owned_base(db, base_id, owner_id)
        return list(
            db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.knowledge_base_id == base_id)
                .order_by(KnowledgeDocument.created_at.desc())
            )
        )
