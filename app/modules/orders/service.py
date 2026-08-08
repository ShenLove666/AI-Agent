from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.framework.errors import AppError
from app.modules.orders.models import CustomerSnapshot, Fulfillment, Order, OrderItem, Refund


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class OrderService:
    """Read-only, owner-scoped order context used by APIs and Agent tools."""

    def detail(self, db: Session, owner_id: int, order_no: str) -> dict:
        order = db.scalar(
            select(Order).where(
                Order.owner_id == owner_id,
                Order.order_no == order_no,
            )
        )
        if order is None:
            raise AppError("ORDER_NOT_FOUND", "订单不存在", 404)

        items = list(
            db.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.id)
            )
        )
        fulfillment = db.scalar(
            select(Fulfillment)
            .where(Fulfillment.order_id == order.id)
            .order_by(Fulfillment.updated_at.desc(), Fulfillment.id.desc())
            .limit(1)
        )
        refund = db.scalar(
            select(Refund)
            .where(Refund.order_id == order.id)
            .order_by(Refund.id.desc())
            .limit(1)
        )
        customer = (
            db.scalar(
                select(CustomerSnapshot).where(
                    CustomerSnapshot.id == order.customer_snapshot_id,
                    CustomerSnapshot.owner_id == owner_id,
                )
            )
            if order.customer_snapshot_id is not None
            else None
        )

        return {
            "id": order.id,
            "orderNo": order.order_no,
            "status": order.status,
            "amount": {
                "currency": order.currency,
                "minor": order.total_amount_minor,
            },
            "placedAt": _iso(order.placed_at),
            "isDemo": order.is_demo,
            "provenance": "synthetic" if order.is_demo else "observed",
            "lineage": _json_object(order.lineage_json),
            "items": [self._item(item) for item in items],
            "fulfillment": self._fulfillment(fulfillment),
            "refund": self._refund(refund),
            "customer": self._customer(customer),
        }

    @staticmethod
    def _item(item: OrderItem) -> dict:
        return {
            "id": item.id,
            "sku": item.sku,
            "productId": item.product_id,
            "productName": item.product_name,
            "quantity": item.quantity,
            "unitPriceMinor": item.unit_price_minor,
            "lineage": _json_object(item.lineage_json),
        }

    @staticmethod
    def _fulfillment(item: Fulfillment | None) -> dict | None:
        if item is None:
            return None
        has_delay_inputs = (
            item.estimated_delivery_at is not None and item.delivered_at is not None
        )
        delay_minutes = (
            max(
                0,
                int(
                    (item.delivered_at - item.estimated_delivery_at).total_seconds()
                    // 60
                ),
            )
            if has_delay_inputs
            else None
        )
        return {
            "id": item.id,
            "status": item.status,
            "carrier": item.carrier,
            "trackingNo": item.tracking_no,
            "estimatedDeliveryAt": _iso(item.estimated_delivery_at),
            "deliveredAt": _iso(item.delivered_at),
            "currentLocation": item.current_location,
            "delayMinutes": delay_minutes,
            "delayProvenance": "derived" if has_delay_inputs else "unavailable",
            "updatedAt": _iso(item.updated_at),
            "lineage": _json_object(item.lineage_json),
        }

    @staticmethod
    def _refund(item: Refund | None) -> dict | None:
        if item is None:
            return None
        return {
            "id": item.id,
            "status": item.status,
            "amountMinor": item.amount_minor,
            "reason": item.reason,
            "requestedAt": _iso(item.requested_at),
            "resolvedAt": _iso(item.resolved_at),
            "lineage": _json_object(item.lineage_json),
        }

    @staticmethod
    def _customer(item: CustomerSnapshot | None) -> dict | None:
        if item is None:
            return None
        return {
            "id": item.id,
            "customerKey": item.customer_key,
            "displayName": item.display_name,
            "tier": item.tier,
            "orderCount": item.order_count,
            "refundCount": item.refund_count,
            "lifetimeValueMinor": item.lifetime_value_minor,
            "capturedAt": _iso(item.captured_at),
            "isDemo": item.is_demo,
            "lineage": _json_object(item.lineage_json),
        }
