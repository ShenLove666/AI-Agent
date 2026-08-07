"""add merchant support quality loop

Revision ID: 0005_support_quality_loop
Revises: 2fce55de2167
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_support_quality_loop"
down_revision = "2fce55de2167"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("case_key", sa.String(80), nullable=False),
        sa.Column("customer_name", sa.String(100), nullable=False),
        sa.Column("customer_channel", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True),
        sa.Column("labels_json", sa.Text(), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("resolution_code", sa.String(50), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "case_key", name="uq_support_case_owner_key"),
    )
    for name, columns in (
        ("ix_support_cases_owner_id", ["owner_id"]),
        ("ix_support_cases_status", ["status"]),
        ("ix_support_cases_priority", ["priority"]),
        ("ix_support_cases_assignee_id", ["assignee_id"]),
        ("ix_support_cases_updated_at", ["updated_at"]),
    ):
        op.create_index(name, "support_cases", columns)
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=True),
        sa.Column("sent_to_customer", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_support_messages_case_id", "support_messages", ["case_id"])
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"])
    op.create_table(
        "support_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (("ix_support_events_owner_id", ["owner_id"]), ("ix_support_events_case_id", ["case_id"]), ("ix_support_events_event_type", ["event_type"]), ("ix_support_events_occurred_at", ["occurred_at"])):
        op.create_index(name, "support_events", columns)
    op.create_table(
        "knowledge_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("processing_status", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("retrieval_mode", sa.String(30), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "version", name="uq_knowledge_release_owner_version"),
    )
    for name, columns in (("ix_knowledge_releases_owner_id", ["owner_id"]), ("ix_knowledge_releases_status", ["status"]), ("ix_knowledge_releases_is_active", ["is_active"])):
        op.create_index(name, "knowledge_releases", columns)
    op.create_table(
        "knowledge_release_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("knowledge_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("filename_snapshot", sa.String(255), nullable=False),
        sa.UniqueConstraint("release_id", "document_id", name="uq_release_document"),
    )
    op.create_index("ix_knowledge_release_documents_release_id", "knowledge_release_documents", ["release_id"])
    op.create_index("ix_knowledge_release_documents_document_id", "knowledge_release_documents", ["document_id"])
    op.create_table(
        "reply_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("knowledge_release_id", sa.Integer(), sa.ForeignKey("knowledge_releases.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=False),
        sa.Column("risk_flags_json", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("config_snapshot_json", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reply_suggestions_case_id", "reply_suggestions", ["case_id"])
    op.create_index("ix_reply_suggestions_status", "reply_suggestions", ["status"])
    op.create_table(
        "reply_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("reply_suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("suggestion_id", name="uq_reply_decision_suggestion"),
    )
    op.create_index("ix_reply_decisions_suggestion_id", "reply_decisions", ["suggestion_id"])
    op.create_index("ix_reply_decisions_case_id", "reply_decisions", ["case_id"])
    op.create_table(
        "support_quality_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("reply_suggestions.id"), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=False),
        sa.Column("failure_category", sa.String(50), nullable=True),
        sa.Column("severity", sa.String(20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (("ix_support_quality_labels_owner_id", ["owner_id"]), ("ix_support_quality_labels_case_id", ["case_id"]), ("ix_support_quality_labels_failure_category", ["failure_category"])):
        op.create_index(name, "support_quality_labels", columns)
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True),
        sa.Column("resolving_release_id", sa.Integer(), sa.ForeignKey("knowledge_releases.id"), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("owner_id", "fingerprint", name="uq_knowledge_gap_owner_fingerprint"),
    )
    for name, columns in (("ix_knowledge_gaps_owner_id", ["owner_id"]), ("ix_knowledge_gaps_category", ["category"]), ("ix_knowledge_gaps_status", ["status"])):
        op.create_index(name, "knowledge_gaps", columns)
    op.create_table(
        "support_release_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("evaluation_run_id", sa.Integer(), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("knowledge_release_id", sa.Integer(), sa.ForeignKey("knowledge_releases.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("gate_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_support_release_decisions_owner_id", "support_release_decisions", ["owner_id"])
    op.create_index("ix_support_release_decisions_evaluation_run_id", "support_release_decisions", ["evaluation_run_id"])
    op.create_index("ix_support_release_decisions_knowledge_release_id", "support_release_decisions", ["knowledge_release_id"])


def downgrade() -> None:
    op.drop_table("support_release_decisions")
    op.drop_table("knowledge_gaps")
    op.drop_table("support_quality_labels")
    op.drop_table("reply_decisions")
    op.drop_table("reply_suggestions")
    op.drop_table("knowledge_release_documents")
    op.drop_table("knowledge_releases")
    op.drop_table("support_events")
    op.drop_table("support_messages")
    op.drop_table("support_cases")
