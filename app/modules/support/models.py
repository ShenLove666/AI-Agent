from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class SupportCase(Base):
    __tablename__ = "support_cases"
    __table_args__ = (UniqueConstraint("owner_id", "case_key", name="uq_support_case_owner_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    case_key: Mapped[str] = mapped_column(String(80))
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_channel: Mapped[str] = mapped_column(String(30), default="web")
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True, index=True)
    labels_json: Mapped[str] = mapped_column(Text, default="[]")
    unread: Mapped[bool] = mapped_column(Boolean, default=True)
    resolution_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    source_data_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id", name="fk_support_case_data_source"), nullable=True, index=True)
    source_record_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generator_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generator_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", name="fk_support_case_order"), nullable=True, index=True)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_to_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SupportEvent(Base):
    __tablename__ = "support_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class KnowledgeRelease(Base):
    __tablename__ = "knowledge_releases"
    __table_args__ = (UniqueConstraint("owner_id", "version", name="uq_knowledge_release_owner_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    version: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    processing_status: Mapped[str] = mapped_column(String(30), default="ready")
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieval_mode: Mapped[str] = mapped_column(String(30), default="keyword")
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeReleaseDocument(Base):
    __tablename__ = "knowledge_release_documents"
    __table_args__ = (UniqueConstraint("release_id", "document_id", name="uq_release_document"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("knowledge_releases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    document_hash: Mapped[str] = mapped_column(String(64))
    filename_snapshot: Mapped[str] = mapped_column(String(255))


class ReplySuggestion(Base):
    __tablename__ = "reply_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users_v2.id"))
    knowledge_release_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_releases.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    model_id: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    config_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReplyDecision(Base):
    __tablename__ = "reply_decisions"
    __table_args__ = (UniqueConstraint("suggestion_id", name="uq_reply_decision_suggestion"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("reply_suggestions.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"))
    decision: Mapped[str] = mapped_column(String(20))
    final_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportQualityLabel(Base):
    __tablename__ = "support_quality_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("reply_suggestions.id"), nullable=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"))
    verdict: Mapped[str] = mapped_column(String(30))
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    __table_args__ = (UniqueConstraint("owner_id", "fingerprint", name="uq_knowledge_gap_owner_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    resolving_release_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_releases.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupportReleaseDecision(Base):
    __tablename__ = "support_release_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    evaluation_run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id"), index=True)
    knowledge_release_id: Mapped[int] = mapped_column(ForeignKey("knowledge_releases.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"))
    decision: Mapped[str] = mapped_column(String(20))
    gate_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
