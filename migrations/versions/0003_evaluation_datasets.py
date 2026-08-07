"""add evaluation datasets

Revision ID: 0003_evaluation_datasets
Revises: 0002_demo_source_metadata
Create Date: 2026-08-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_evaluation_datasets"
down_revision: Union[str, Sequence[str], None] = "0002_demo_source_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_evaluation_dataset_owner_name"),
    )
    op.create_index("ix_evaluation_datasets_owner_id", "evaluation_datasets", ["owner_id"])
    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            sa.ForeignKey("evaluation_datasets.id"),
            nullable=False,
        ),
        sa.Column("case_key", sa.String(length=100), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("difficulty", sa.String(length=50), nullable=False),
        sa.Column("knowledge_base_ids_json", sa.Text(), nullable=False),
        sa.Column("expected_points_json", sa.Text(), nullable=False),
        sa.Column("expected_document_keys_json", sa.Text(), nullable=False),
        sa.Column("should_refuse", sa.Boolean(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dataset_id", "case_key", name="uq_evaluation_case_dataset_key"),
    )
    op.create_index("ix_evaluation_cases_dataset_id", "evaluation_cases", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_cases_dataset_id", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index("ix_evaluation_datasets_owner_id", table_name="evaluation_datasets")
    op.drop_table("evaluation_datasets")
