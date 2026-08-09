from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class MerchantProfile(Base):
    __tablename__ = "merchant_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    business_type: Mapped[str] = mapped_column(String(50), default="即时零售商超")
    store_count: Mapped[int] = mapped_column(Integer, default=3)
    goal: Mapped[str] = mapped_column(Text, default="提升连带购并降低活动咨询转人工率")
    stage: Mapped[str] = mapped_column(String(30), default="optimizing")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CommerceImport(Base):
    __tablename__ = "commerce_imports"
    __table_args__ = (UniqueConstraint("owner_id", "fingerprint", name="uq_commerce_import_owner_fingerprint"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(100), default="groceries-shopping-baskets")
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    source_row_count: Mapped[int] = mapped_column(Integer)
    basket_count: Mapped[int] = mapped_column(Integer)
    product_count: Mapped[int] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id", name="fk_commerce_import_data_source"), nullable=True, index=True)
    accepted_row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rejected_row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    quality_report_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class Product(Base):
    __tablename__ = "commerce_products"
    __table_args__ = (UniqueConstraint("owner_id", "source_key", name="uq_commerce_product_owner_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(100), default="未分类")
    data_origin: Mapped[str] = mapped_column(String(20), default="source")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    provenance: Mapped[str] = mapped_column(String(20), default="observed", server_default="observed")
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class Basket(Base):
    __tablename__ = "commerce_baskets"
    __table_args__ = (UniqueConstraint("import_id", "source_basket_key", name="uq_commerce_basket_import_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("commerce_imports.id"), index=True)
    source_basket_key: Mapped[str] = mapped_column(String(100))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    store_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    data_origin: Mapped[str] = mapped_column(String(20), default="source")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    provenance: Mapped[str] = mapped_column(String(20), default="observed", server_default="observed")
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    customer_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class BasketItem(Base):
    __tablename__ = "commerce_basket_items"
    __table_args__ = (UniqueConstraint("basket_id", "source_row_key", name="uq_commerce_item_basket_row"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    basket_id: Mapped[int] = mapped_column(ForeignKey("commerce_baskets.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("commerce_products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_row_key: Mapped[str] = mapped_column(String(50))
    data_origin: Mapped[str] = mapped_column(String(20), default="source")
    provenance: Mapped[str] = mapped_column(String(20), default="observed", server_default="observed")
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class AssociationRule(Base):
    __tablename__ = "commerce_association_rules"
    __table_args__ = (UniqueConstraint("import_id", "antecedent_product_id", "consequent_product_id", name="uq_commerce_rule_pair"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("commerce_imports.id"), index=True)
    antecedent_product_id: Mapped[int] = mapped_column(ForeignKey("commerce_products.id"))
    consequent_product_id: Mapped[int] = mapped_column(ForeignKey("commerce_products.id"))
    cooccurrence_count: Mapped[int] = mapped_column(Integer)
    support: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    lift: Mapped[float] = mapped_column(Float, index=True)
    min_count: Mapped[int] = mapped_column(Integer, default=60)
    fingerprint: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "commerce_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("commerce_association_rules.id"))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # 方案生命周期扩展（0009 迁移追加列，顺序与迁移保持一致）
    lock_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1"
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CampaignVersion(Base):
    __tablename__ = "commerce_campaign_versions"
    __table_args__ = (UniqueConstraint("campaign_id", "version", name="uq_campaign_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("commerce_campaigns.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(30), default="即时零售")
    copy: Mapped[str] = mapped_column(Text)
    rule_snapshot_json: Mapped[str] = mapped_column(Text)
    knowledge_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users_v2.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
