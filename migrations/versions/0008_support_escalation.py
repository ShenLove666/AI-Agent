"""add support escalation lifecycle

Revision ID: 0008_support_escalation
Revises: 0007_v3_order_outbound
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_support_escalation"
down_revision = "0007_v3_order_outbound"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False
        ),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("support_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raised_by", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False
        ),
        sa.Column(
            "assigned_to", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("resolution", sa.String(50), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("ai_diagnosis_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("raised_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "case_id", "raised_at", name="uq_support_escalation_case_raised"
        ),
    )
    op.create_index(
        "ix_support_escalations_owner_id", "support_escalations", ["owner_id"]
    )
    op.create_index(
        "ix_support_escalations_case_id", "support_escalations", ["case_id"]
    )
    op.create_index("ix_support_escalations_status", "support_escalations", ["status"])
    op.create_index(
        "ix_support_escalations_category", "support_escalations", ["category"]
    )
    op.create_index(
        "ix_support_escalations_assigned_to", "support_escalations", ["assigned_to"]
    )


def downgrade() -> None:
    op.drop_table("support_escalations")
