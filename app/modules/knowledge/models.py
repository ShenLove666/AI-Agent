from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.framework.database import Base


CONTENT_ORIGINS = frozenset({"user_upload", "public_summary", "synthetic"})


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(30))
    storage_path: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    content_origin: Mapped[str] = mapped_column(
        String(30),
        default="user_upload",
        server_default=text("'user_upload'"),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_retrieved_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @validates("content_origin")
    def validate_content_origin(self, _key: str, value: str) -> str:
        if value not in CONTENT_ORIGINS:
            allowed = ", ".join(sorted(CONTENT_ORIGINS))
            raise ValueError(f"content_origin must be one of: {allowed}")
        return value


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
