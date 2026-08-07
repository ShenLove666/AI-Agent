"""add truthful retail data provenance

Revision ID: 0006_retail_data_provenance
Revises: 0005_support_quality_loop
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_retail_data_provenance"
down_revision = "0005_support_quality_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("dataset_key", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("source_uri", sa.String(1000), nullable=False),
        sa.Column("publisher", sa.String(255), nullable=False),
        sa.Column("license", sa.String(120), nullable=False),
        sa.Column("retrieved_at", sa.Date(), nullable=False),
        sa.Column("encoding", sa.String(40), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("limitations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("transform_version", sa.String(80), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "dataset_key", "version", name="uq_data_source_owner_key_version"),
    )
    op.create_index("ix_data_sources_owner_id", "data_sources", ["owner_id"])

    _add("commerce_imports", sa.Column("data_source_id", sa.Integer(), sa.ForeignKey("data_sources.id", name="fk_commerce_import_data_source"), nullable=True))
    _add("commerce_imports", sa.Column("accepted_row_count", sa.Integer(), nullable=False, server_default="0"))
    _add("commerce_imports", sa.Column("rejected_row_count", sa.Integer(), nullable=False, server_default="0"))
    _add("commerce_imports", sa.Column("quality_report_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index("ix_commerce_imports_data_source_id", "commerce_imports", ["data_source_id"])

    for table in ("commerce_products", "commerce_baskets", "commerce_basket_items"):
        _add(table, sa.Column("provenance", sa.String(20), nullable=False, server_default="observed"))
        _add(table, sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"))
    _add("commerce_baskets", sa.Column("customer_key", sa.String(100), nullable=True))
    _add("commerce_baskets", sa.Column("country", sa.String(100), nullable=True))
    _add("commerce_baskets", sa.Column("invoice_status", sa.String(30), nullable=True))

    _add("support_cases", sa.Column("source_data_id", sa.Integer(), sa.ForeignKey("data_sources.id", name="fk_support_case_data_source"), nullable=True))
    _add("support_cases", sa.Column("source_record_key", sa.String(120), nullable=True))
    _add("support_cases", sa.Column("generator_version", sa.String(80), nullable=True))
    _add("support_cases", sa.Column("generator_seed", sa.Integer(), nullable=True))
    _add("support_cases", sa.Column("field_lineage_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index("ix_support_cases_source_data_id", "support_cases", ["source_data_id"])

    _add("knowledge_documents", sa.Column("source_title", sa.String(500), nullable=True))
    _add("knowledge_documents", sa.Column("source_jurisdiction", sa.String(120), nullable=True))
    _add("knowledge_documents", sa.Column("source_effective_at", sa.Date(), nullable=True))
    _add("knowledge_documents", sa.Column("next_review_at", sa.Date(), nullable=True))
    _add("knowledge_documents", sa.Column("review_status", sa.String(30), nullable=False, server_default="current"))
    _add("knowledge_documents", sa.Column("applicability_json", sa.Text(), nullable=False, server_default="[]"))
    _add("knowledge_documents", sa.Column("exclusions_json", sa.Text(), nullable=False, server_default="[]"))
    _add("knowledge_documents", sa.Column("license_or_usage_note", sa.Text(), nullable=True))

    # Legacy commerce import generated plausible timestamps, channels, stores and prices.
    # Preserve the rows but explicitly classify those fields as synthetic.
    op.execute("UPDATE commerce_baskets SET provenance='synthetic', lineage_json='{\"basketMembership\":{\"provenance\":\"observed\"},\"orderedAt\":{\"provenance\":\"synthetic\",\"reason\":\"legacy_seed\"},\"storeKey\":{\"provenance\":\"synthetic\",\"reason\":\"legacy_seed\"},\"channel\":{\"provenance\":\"synthetic\",\"reason\":\"legacy_seed\"}}' WHERE data_origin='source'")
    op.execute("UPDATE commerce_basket_items SET provenance='synthetic', lineage_json='{\"product\":{\"provenance\":\"observed\"},\"quantity\":{\"provenance\":\"synthetic\",\"reason\":\"legacy_default\"},\"unitPrice\":{\"provenance\":\"synthetic\",\"reason\":\"legacy_seed\"}}' WHERE data_origin='source'")


def downgrade() -> None:
    for name in (
        "license_or_usage_note", "exclusions_json", "applicability_json", "review_status",
        "next_review_at", "source_effective_at", "source_jurisdiction", "source_title",
    ):
        _drop("knowledge_documents", name)
    op.drop_index("ix_support_cases_source_data_id", table_name="support_cases")
    for name in ("field_lineage_json", "generator_seed", "generator_version", "source_record_key", "source_data_id"):
        _drop("support_cases", name)
    for name in ("invoice_status", "country", "customer_key"):
        _drop("commerce_baskets", name)
    for table in ("commerce_basket_items", "commerce_baskets", "commerce_products"):
        _drop(table, "lineage_json")
        _drop(table, "provenance")
    op.drop_index("ix_commerce_imports_data_source_id", table_name="commerce_imports")
    for name in ("quality_report_json", "rejected_row_count", "accepted_row_count", "data_source_id"):
        _drop("commerce_imports", name)
    op.drop_index("ix_data_sources_owner_id", table_name="data_sources")
    op.drop_table("data_sources")


def _add(table: str, column: sa.Column) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(column)


def _drop(table: str, column: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_column(column)
