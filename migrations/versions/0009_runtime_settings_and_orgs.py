"""runtime settings, organizations, campaign lifecycle, task backfill

Revision ID: 0009_runtime_settings_and_orgs
Revises: 0008_support_escalation
Create Date: 2026-08-09
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "0009_runtime_settings_and_orgs"
down_revision = "0008_support_escalation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 运行时配置（可持久化、版本化、审计） ----
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column(
            "updated_by", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key", name="uq_runtime_settings_key"),
    )
    op.create_table(
        "runtime_settings_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("old_value_json", sa.Text(), nullable=True),
        sa.Column("new_value_json", sa.Text(), nullable=True),
        sa.Column(
            "operator_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=True
        ),
        sa.Column("operator_name", sa.String(50), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_runtime_settings_audit_key", "runtime_settings_audit", ["key"]
    )
    op.create_table(
        "runtime_config_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO runtime_config_meta (id, version) VALUES (1, 1)")

    # ---- 商家组织-成员关系 ----
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "owner_user_id", sa.Integer(), sa.ForeignKey("users_v2.id"), nullable=False
        ),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_organizations_owner_user_id",
        "organizations",
        ["owner_user_id"],
        unique=True,
    )
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_member_org_user"),
    )
    op.create_index("ix_organization_members_org_id", "organization_members", ["org_id"])
    op.create_index(
        "ix_organization_members_user_id", "organization_members", ["user_id"]
    )

    # ---- 方案生命周期扩展 ----
    # SQLite 给非空表加 NOT NULL 列必须带默认值；models 与迁移保持一致
    op.add_column(
        "commerce_campaigns",
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "commerce_campaigns",
        sa.Column("rejected_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "commerce_campaigns",
        sa.Column("published_at", sa.DateTime(), nullable=True),
    )

    # ---- 数据回填：为现有已确认/已发布方案与失败评测补建优化任务 ----
    _backfill_tasks()


def _backfill_tasks() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    campaigns = sa.Table("commerce_campaigns", meta, autoload_with=bind)
    tasks = sa.Table("optimization_tasks", meta, autoload_with=bind)
    runs = sa.Table("evaluation_runs", meta, autoload_with=bind)
    results = sa.Table("evaluation_results", meta, autoload_with=bind)

    now = sa.func.datetime("now")

    # 1) 已确认/已发布的方案 → 验证与发布任务
    rows = bind.execute(
        sa.select(
            campaigns.c.id, campaigns.c.owner_id, campaigns.c.name, campaigns.c.rule_id
        ).where(campaigns.c.status.in_(["confirmed", "published"]))
    ).fetchall()
    for campaign_id, owner_id, name, rule_id in rows:
        exists = bind.execute(
            sa.select(sa.literal(1)).where(
                tasks.c.owner_id == owner_id,
                tasks.c.source_type == "campaign",
                tasks.c.source_id == sa.cast(campaign_id, sa.String),
            )
        ).first()
        if exists:
            continue
        bind.execute(
            tasks.insert().values(
                owner_id=owner_id,
                source_type="campaign",
                source_id=str(campaign_id),
                title=f"验证并跟进方案：{name}",
                status="new",
                target_metric="搭配购采用率",
                before_evidence_json=json.dumps(
                    {"origin": "campaign_backfill"}, ensure_ascii=False
                ),
                after_evidence_json="{}",
                is_demo=True,
                association_rule_id=rule_id,
                created_at=now,
                updated_at=now,
            )
        )

    # 2) 存在失败用例的评测运行 → 复测任务
    failed_run_ids = bind.execute(
        sa.select(results.c.run_id)
        .where(results.c.expected_point_score < 100)
        .group_by(results.c.run_id)
    ).scalars().all()
    if not failed_run_ids:
        return
    run_rows = bind.execute(
        sa.select(runs.c.id, runs.c.owner_id).where(runs.c.id.in_(failed_run_ids))
    ).fetchall()
    for run_id, owner_id in run_rows:
        exists = bind.execute(
            sa.select(sa.literal(1)).where(
                tasks.c.owner_id == owner_id,
                tasks.c.source_type == "evaluation",
                tasks.c.source_id == sa.cast(run_id, sa.String),
            )
        ).first()
        if exists:
            continue
        bind.execute(
            tasks.insert().values(
                owner_id=owner_id,
                source_type="evaluation",
                source_id=str(run_id),
                title=f"评测失败复测与修复（评测运行 #{run_id}）",
                status="new",
                target_metric="评测通过率",
                before_evidence_json=json.dumps(
                    {"origin": "evaluation_backfill", "runId": run_id},
                    ensure_ascii=False,
                ),
                after_evidence_json="{}",
                is_demo=True,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.drop_table("runtime_config_meta")
    op.drop_index("ix_runtime_settings_audit_key", table_name="runtime_settings_audit")
    op.drop_table("runtime_settings_audit")
    op.drop_table("runtime_settings")
    op.drop_column("commerce_campaigns", "published_at")
    op.drop_column("commerce_campaigns", "rejected_reason")
    op.drop_column("commerce_campaigns", "lock_version")
