"""create optimization_verification_runs and explicit task FKs

AI 评测（evaluation_runs）与经营效果复测彻底分离：
- 新表 optimization_verification_runs：方案发布前后窗口的指标对比
  （before/after 值、样本量、窗口、方法论），与回答质量评测解耦；
- optimization_tasks 追加 ai_evaluation_run_id（→ evaluation_runs）与
  business_verification_run_id（→ optimization_verification_runs）两个显式 FK。
- 遗留列 verification_run_id 保留（历史数据兼容），不再写入新值。

Revision ID: 0016_optimization_verification_runs
Revises: 0015_trace_run_ttft
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_optimization_verification_runs"
down_revision = "0015_trace_run_ttft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "optimization_verification_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("baseline_start", sa.DateTime(), nullable=True),
        sa.Column("baseline_end", sa.DateTime(), nullable=True),
        sa.Column("experiment_start", sa.DateTime(), nullable=True),
        sa.Column("experiment_end", sa.DateTime(), nullable=True),
        sa.Column("before_value", sa.Float(), nullable=True),
        sa.Column("after_value", sa.Float(), nullable=True),
        sa.Column("delta_value", sa.Float(), nullable=True),
        sa.Column("delta_rate", sa.Float(), nullable=True),
        sa.Column("baseline_sample_size", sa.Integer(), nullable=True),
        sa.Column("experiment_sample_size", sa.Integer(), nullable=True),
        sa.Column("methodology_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users_v2.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["optimization_tasks.id"]),
    )
    op.create_index(
        "ix_optimization_verification_runs_owner_id",
        "optimization_verification_runs",
        ["owner_id"],
    )
    op.create_index(
        "ix_optimization_verification_runs_task_id",
        "optimization_verification_runs",
        ["task_id"],
    )
    # SQLite 不支持对已有表 ADD COLUMN 带 FK（静默丢弃），用 batch 模式重建表：
    # 保留数据与既有约束，同时补上两个显式外键与索引。
    with op.batch_alter_table("optimization_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("ai_evaluation_run_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("business_verification_run_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_optimization_task_ai_eval_run",
            "evaluation_runs",
            ["ai_evaluation_run_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_optimization_task_business_verify",
            "optimization_verification_runs",
            ["business_verification_run_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_optimization_tasks_ai_evaluation_run_id", ["ai_evaluation_run_id"]
        )
        batch_op.create_index(
            "ix_optimization_tasks_business_verification_run_id",
            ["business_verification_run_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("optimization_tasks") as batch_op:
        batch_op.drop_index("ix_optimization_tasks_business_verification_run_id")
        batch_op.drop_index("ix_optimization_tasks_ai_evaluation_run_id")
        batch_op.drop_column("business_verification_run_id")
        batch_op.drop_column("ai_evaluation_run_id")
    op.drop_index(
        "ix_optimization_verification_runs_task_id", "optimization_verification_runs"
    )
    op.drop_index(
        "ix_optimization_verification_runs_owner_id", "optimization_verification_runs"
    )
    op.drop_table("optimization_verification_runs")
