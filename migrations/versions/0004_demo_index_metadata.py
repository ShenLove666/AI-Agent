"""add demo index reconciliation metadata

Revision ID: 0004_demo_index_metadata
Revises: 0003_evaluation_datasets
Create Date: 2026-08-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_demo_index_metadata"
down_revision: Union[str, Sequence[str], None] = "0003_evaluation_datasets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("demo_content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("demo_indexed_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "vector_indexed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "vector_indexed")
    op.drop_column("knowledge_documents", "demo_indexed_sha256")
    op.drop_column("knowledge_documents", "demo_content_sha256")
