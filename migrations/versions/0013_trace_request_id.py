"""add request_id to rag_trace_runs

Trace 之前无法展示「任务/请求 ID」：RagTraceRun 没有 request_id 列，
API 硬编码 taskId=None。本迁移新增 request_id 列（索引）——trace 创建时
写入聊天请求的 request_id（幂等/防重复提交的请求指纹），让 Trace 真正
关联到完整业务链路（Trace → Request → Conversation → Turn）。

Revision ID: 0013_trace_request_id
Revises: 0012_repair_knowledge_owner_and_source_kind
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_trace_request_id"
down_revision = "0012_repair_knowledge_owner_and_source_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_trace_runs",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_rag_trace_runs_request_id", "rag_trace_runs", ["request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_rag_trace_runs_request_id", table_name="rag_trace_runs")
    op.drop_column("rag_trace_runs", "request_id")
