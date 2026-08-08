from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.framework.database import Base


class OptimizationTask(Base):
    __tablename__ = "optimization_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    target_metric: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verification_run_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_runs.id"), nullable=True)
    before_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    after_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    association_rule_id: Mapped[int | None] = mapped_column(ForeignKey("commerce_association_rules.id", name="fk_optimization_task_rule"), nullable=True, index=True)
    support_case_id: Mapped[int | None] = mapped_column(ForeignKey("support_cases.id", name="fk_optimization_task_support_case"), nullable=True, index=True)
