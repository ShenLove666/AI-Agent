"""add start_offset_ms to rag_trace_nodes

Trace Waterfall 之前全部节点 @0ms：节点只记录了 duration（elapsed_ms），
没有相对 Trace 起点的偏移，前端不知道 Generation 是第几毫秒开始的。
本迁移新增 start_offset_ms（节点相对 trace.start 的偏移，毫秒）——
trace_service.node 写入，API 依此计算真实 startTime/endTime。

Revision ID: 0014_trace_node_start_offset
Revises: 0013_trace_request_id
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_trace_node_start_offset"
down_revision = "0013_trace_request_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_trace_nodes",
        sa.Column("start_offset_ms", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("rag_trace_nodes", "start_offset_ms")
