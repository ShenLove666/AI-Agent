"""add ttft_ms to rag_trace_runs

列表页「平均首字」长期显示 —：generation 节点把 ttft_ms 算好后只写进
attributes_json，列表 API 只读 RagTraceRun（run_vo 硬编码 ttftMs=None）。
TTFT 是 Run 级核心指标，直接落到 rag_trace_runs，列表接口无需解析
Node JSON（避免 N+1）。

Revision ID: 0015_trace_run_ttft
Revises: 0014_trace_node_start_offset
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_trace_run_ttft"
down_revision = "0014_trace_node_start_offset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_trace_runs",
        sa.Column("ttft_ms", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rag_trace_runs", "ttft_ms")
