from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


PROVENANCE_VALUES = frozenset({"observed", "derived", "synthetic"})


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("owner_id", "dataset_key", "version", name="uq_data_source_owner_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    dataset_key: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(30))
    source_uri: Mapped[str] = mapped_column(String(1000))
    publisher: Mapped[str] = mapped_column(String(255))
    license: Mapped[str] = mapped_column(String(120))
    retrieved_at: Mapped[date] = mapped_column(Date)
    encoding: Mapped[str] = mapped_column(String(40))
    schema_json: Mapped[str] = mapped_column(Text)
    limitations_json: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    transform_version: Mapped[str] = mapped_column(String(80))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
