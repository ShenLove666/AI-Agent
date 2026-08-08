"""add V3 order context and outbound delivery

Revision ID: 0007_v3_order_outbound
Revises: 0006_retail_data_provenance
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_v3_order_outbound"
down_revision = "0006_retail_data_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("customer_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("tier", sa.String(30), nullable=True),
        sa.Column("order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refund_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_value_minor", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("owner_id", "customer_key", name="uq_customer_snapshot_owner_key"),
    )
    op.create_index("ix_customer_snapshots_owner_id", "customer_snapshots", ["owner_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("order_no", sa.String(80), nullable=False),
        sa.Column("customer_snapshot_id", sa.Integer(), sa.ForeignKey("customer_snapshots.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "order_no", name="uq_order_owner_no"),
    )
    op.create_index("ix_orders_owner_id", "orders", ["owner_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_customer_snapshot_id", "orders", ["customer_snapshot_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("commerce_products.id"), nullable=True),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("product_name", sa.String(160), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "fulfillments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("carrier", sa.String(80), nullable=True),
        sa.Column("tracking_no", sa.String(100), nullable=True),
        sa.Column("estimated_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("current_location", sa.String(200), nullable=True),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fulfillments_order_id", "fulfillments", ["order_id"])
    op.create_index("ix_fulfillments_status", "fulfillments", ["status"])

    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_status", "refunds", ["status"])

    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("support_message_id", sa.Integer(), sa.ForeignKey("support_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("reply_suggestions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_outbound_owner_idempotency"),
    )
    op.create_index("ix_outbound_messages_owner_id", "outbound_messages", ["owner_id"])
    op.create_index("ix_outbound_messages_case_id", "outbound_messages", ["case_id"])
    op.create_index("ix_outbound_messages_status", "outbound_messages", ["status"])

    _add("support_cases", sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", name="fk_support_case_order"), nullable=True))
    op.create_index("ix_support_cases_order_id", "support_cases", ["order_id"])
    _add("optimization_tasks", sa.Column("association_rule_id", sa.Integer(), sa.ForeignKey("commerce_association_rules.id", name="fk_optimization_task_rule"), nullable=True))
    _add("optimization_tasks", sa.Column("support_case_id", sa.Integer(), sa.ForeignKey("support_cases.id", name="fk_optimization_task_support_case"), nullable=True))
    op.create_index("ix_optimization_tasks_association_rule_id", "optimization_tasks", ["association_rule_id"])
    op.create_index("ix_optimization_tasks_support_case_id", "optimization_tasks", ["support_case_id"])


def downgrade() -> None:
    op.drop_index("ix_optimization_tasks_support_case_id", table_name="optimization_tasks")
    op.drop_index("ix_optimization_tasks_association_rule_id", table_name="optimization_tasks")
    _drop("optimization_tasks", "support_case_id")
    _drop("optimization_tasks", "association_rule_id")
    op.drop_index("ix_support_cases_order_id", table_name="support_cases")
    _drop("support_cases", "order_id")
    op.drop_table("outbound_messages")
    op.drop_table("refunds")
    op.drop_table("fulfillments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("customer_snapshots")


def _add(table: str, column: sa.Column) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)


def _drop(table: str, column: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_column(column)
