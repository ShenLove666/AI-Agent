from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class RagTraceRun(Base):
    __tablename__ = "rag_trace_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 聊天请求去重指纹（ChatRequestRun.request_id）：Trace → Request → Conversation → Turn。
    # 位于末尾：与 migration 0013 的 add_column（SQLite 追加到表尾）列顺序一致。
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 首 Token 延迟（Generation 开始 → 首个正式回答 Token）。Run 级指标，
    # 列表 API 直接读取（避免解析 Node JSON 的 N+1）。位于末尾与迁移一致。
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class RagTraceNode(Base):
    __tablename__ = "rag_trace_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rag_trace_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    elapsed_ms: Mapped[float] = mapped_column(Float)
    attributes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 相对 trace.start 的偏移（毫秒）：Waterfall 真实时序的依据。
    # 位于末尾：与 migration 0014 的 add_column（SQLite 追加到表尾）列顺序一致；
    # server_default 与迁移保持一致（legacy 重建签名比对）。
    start_offset_ms: Mapped[float] = mapped_column(
        Float, default=0, server_default="0"
    )
