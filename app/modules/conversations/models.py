from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_turn_conversation_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    user_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    active_assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="processing")
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deep_thinking: Mapped[bool] = mapped_column(Boolean, default=False)
    knowledge_base_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_turns.id"), nullable=True, index=True
    )
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    vote: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 用户反馈: 1 赞 / -1 踩
    message_status: Mapped[str] = mapped_column(String(30), default="NORMAL")
    thinking_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_questions_status: Mapped[str] = mapped_column(
        String(20), default="NOT_REQUESTED"
    )
    recommended_questions_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Agent 执行摘要（JSON 文本，可空）：由迁移 0010 追加在表末尾，
    # 需保持为模型最后一个字段以匹配 SQLite ALTER TABLE 的列顺序。
    agent_execution_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatRequestRun(Base):
    __tablename__ = "chat_request_runs"
    __table_args__ = (UniqueConstraint("user_id", "request_id", name="uq_chat_request_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(64))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    requested_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_turns.id"), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    user_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
