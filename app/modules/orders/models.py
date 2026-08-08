from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.framework.database import Base


class CustomerSnapshot(Base):
    __tablename__ = "customer_snapshots"
    __table_args__ = (UniqueConstraint("owner_id", "customer_key", name="uq_customer_snapshot_owner_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    customer_key: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(120))
    tier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    refund_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lifetime_value_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("owner_id", "order_no", name="uq_order_owner_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    order_no: Mapped[str] = mapped_column(String(80))
    customer_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("customer_snapshots.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", server_default="CNY")
    total_amount_minor: Mapped[int] = mapped_column(Integer)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("commerce_products.id"), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(Integer)
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class Fulfillment(Base):
    __tablename__ = "fulfillments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    carrier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lineage_json: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_outbound_owner_idempotency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users_v2.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("support_cases.id", ondelete="CASCADE"), index=True)
    support_message_id: Mapped[int | None] = mapped_column(ForeignKey("support_messages.id", ondelete="SET NULL"), nullable=True)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("reply_suggestions.id", ondelete="SET NULL"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    content: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
