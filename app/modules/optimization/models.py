from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    # AI 评测与经营效果复测显式分离（迁移 0016）：ai_evaluation_run_id 关联
    # evaluation_runs（回答质量评测）；business_verification_run_id 关联
    # optimization_verification_runs（方案前后窗口经营指标对比）。
    # verification_run_id 为遗留列（历史数据兼容），不再写入新值。
    ai_evaluation_run_id: Mapped[int | None] = mapped_column(ForeignKey("evaluation_runs.id", name="fk_optimization_task_ai_eval_run"), nullable=True, index=True)
    business_verification_run_id: Mapped[int | None] = mapped_column(ForeignKey("optimization_verification_runs.id", name="fk_optimization_task_business_verify"), nullable=True, index=True)


class OptimizationVerificationRun(Base):
    """经营效果复测运行：方案发布前后窗口的指标对比（与 AI 评测彻底分离）。

    记录 before/after 值、样本量与窗口，保证「8.2% → 10.7%」有定义、有样本、
    可解释；无可用经营数据时 status=insufficient_data，methodology_json 说明原因。
    """

    __tablename__ = "optimization_verification_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("optimization_tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="running")  # running/completed/insufficient_data/failed
    metric_key: Mapped[str] = mapped_column(String(100))
    baseline_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    baseline_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    experiment_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    experiment_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    before_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experiment_sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    methodology_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
