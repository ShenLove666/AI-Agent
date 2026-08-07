from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.framework.database import Base


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_evaluation_dataset_owner_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    cases: Mapped[list[EvaluationCase]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="EvaluationCase.id"
    )


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_key", name="uq_evaluation_case_dataset_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("evaluation_datasets.id"), index=True)
    case_key: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[str] = mapped_column(String(50))
    knowledge_base_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_points_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_document_keys_json: Mapped[str] = mapped_column(Text, default="[]")
    should_refuse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    dataset: Mapped[EvaluationDataset] = relationship(back_populates="cases")

    @property
    def knowledge_base_ids(self) -> list[int]:
        return [int(value) for value in json.loads(self.knowledge_base_ids_json)]

    @property
    def expected_points(self) -> list[str]:
        return [str(value) for value in json.loads(self.expected_points_json)]

    @property
    def expected_document_keys(self) -> list[str]:
        return [str(value) for value in json.loads(self.expected_document_keys_json)]


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("evaluation_datasets.id"), index=True)
    campaign_version_id: Mapped[int | None] = mapped_column(ForeignKey("commerce_campaign_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    config_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_evaluation_result_run_case"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("evaluation_cases.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    expected_point_score: Mapped[int] = mapped_column(Integer, default=0)
    citation_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    refusal_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")


class EvaluationLabel(Base):
    __tablename__ = "evaluation_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("evaluation_results.id", ondelete="CASCADE"), unique=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"))
    verdict: Mapped[str] = mapped_column(String(20))
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
