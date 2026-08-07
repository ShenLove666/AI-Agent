from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.framework.database import Base


class OperationEvent(Base):
    __tablename__ = "operation_events"
    __table_args__ = (UniqueConstraint("owner_id", "event_key", name="uq_operation_event_owner_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    campaign_version_id: Mapped[int | None] = mapped_column(ForeignKey("commerce_campaign_versions.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    data_origin: Mapped[str] = mapped_column(String(20), default="synthetic")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
