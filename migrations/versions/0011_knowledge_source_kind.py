"""knowledge document source_kind column

Revision ID: 0011_knowledge_source_kind
Revises: 0010_agent_execution_summary
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_knowledge_source_kind"
down_revision = "0010_agent_execution_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_kind",
            sa.String(length=40),
            server_default="general",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "source_kind")
