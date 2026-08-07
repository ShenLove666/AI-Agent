"""add demo ownership and source provenance

Revision ID: 0002_demo_source_metadata
Revises: 0001_current_schema
Create Date: 2026-08-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_demo_source_metadata"
down_revision: Union[str, Sequence[str], None] = "0001_current_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users_v2",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "content_origin",
            sa.String(length=30),
            nullable=False,
            server_default="user_upload",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_publisher", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_retrieved_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_usage_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "source_usage_note")
    op.drop_column("knowledge_documents", "source_retrieved_at")
    op.drop_column("knowledge_documents", "source_publisher")
    op.drop_column("knowledge_documents", "source_url")
    op.drop_column("knowledge_documents", "content_origin")
    op.drop_column("users_v2", "is_demo")
