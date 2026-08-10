"""repair knowledge owner attribution and backfill source_kind

历史数据修复（幂等，可重复执行）：

1. owner 修复：knowledge_bases.owner_id 若指向「组织成员」（organization_members
   的 user_id，即 owner 归错为成员 id 而非组织 owner），则通过该成员所属组织
   的 organizations.owner_user_id 修正；无对应 org 或 org owner 缺失/与当前
   owner 相同（已是正确归属）的记录一律跳过（安全迁移，不猜不删）。

2. source_kind backfill：对 knowledge_documents.source_kind 为 'general'（或
   NULL）的旧文档，按 filename / 所属 KB 名称用与 service.infer_source_kind
   等价的规则回填（policy → 政策/规则/退货/退款/售后；recommendation_guide →
   指南/推荐/搭配；product_knowledge → 商品/说明；其余保持 general）。
   注意：与 app/modules/knowledge/service.py 的 infer_source_kind 保持一致，
   若后续调整规则需同步本迁移。

Revision ID: 0012_repair_knowledge_owner_and_source_kind
Revises: 0011_knowledge_source_kind
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_repair_knowledge_owner_and_source_kind"
down_revision = "0011_knowledge_source_kind"
branch_labels = None
depends_on = None


# 与 service.infer_source_kind 的规则一致（顺序即优先级）：
# policy → recommendation_guide → product_knowledge → 保持 general。
_SOURCE_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("policy", ("政策", "规则", "退货", "退款", "售后")),
    ("recommendation_guide", ("指南", "推荐", "搭配")),
    ("product_knowledge", ("商品", "说明")),
)


def _repair_base_owners(connection) -> None:
    """owner 归错修复：成员 id → 组织 owner（幂等）。"""
    rows = connection.execute(
        sa.text(
            """
            SELECT kb.id,
                   (SELECT org.owner_user_id
                    FROM organization_members om
                    JOIN organizations org ON org.id = om.org_id
                    WHERE om.user_id = kb.owner_id
                      AND org.owner_user_id IS NOT NULL
                      AND org.owner_user_id != kb.owner_id
                    ORDER BY om.id ASC
                    LIMIT 1) AS target_owner
            FROM knowledge_bases kb
            WHERE kb.owner_id IN (SELECT user_id FROM organization_members)
            """
        )
    ).fetchall()
    for base_id, target_owner in rows:
        if target_owner is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE knowledge_bases SET owner_id = :owner_id WHERE id = :base_id"
            ),
            {"owner_id": target_owner, "base_id": base_id},
        )


def _backfill_source_kind(connection) -> None:
    """source_kind 回填：仅处理 'general'/NULL 的旧文档（幂等）。"""
    for source_kind, terms in _SOURCE_KIND_RULES:
        matches = " OR ".join(
            "(d.filename LIKE :t{index} OR kb.name LIKE :t{index})".format(index=index)
            for index in range(len(terms))
        )
        rows = connection.execute(
            sa.text(
                f"""
                SELECT d.id
                FROM knowledge_documents d
                JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
                WHERE (d.source_kind IS NULL OR d.source_kind = 'general')
                  AND ({matches})
                """
            ),
            {f"t{index}": f"%{term}%" for index, term in enumerate(terms)},
        ).fetchall()
        for (document_id,) in rows:
            connection.execute(
                sa.text(
                    "UPDATE knowledge_documents SET source_kind = :kind WHERE id = :doc_id"
                ),
                {"kind": source_kind, "doc_id": document_id},
            )


def upgrade() -> None:
    connection = op.get_bind()
    _repair_base_owners(connection)
    _backfill_source_kind(connection)


def downgrade() -> None:
    # 数据修复不可安全回滚（owner 修正与 source_kind 回填无法可靠还原），
    # downgrade 为空操作；表结构本身未变化。
    pass
