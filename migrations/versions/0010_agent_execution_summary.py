"""agent execution summary on messages

Revision ID: 0010_agent_execution_summary
Revises: 0009_runtime_settings_and_orgs
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_agent_execution_summary"
down_revision = "0009_runtime_settings_and_orgs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("agent_execution_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "agent_execution_json")
