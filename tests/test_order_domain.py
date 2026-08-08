from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import event

import app.application_core  # noqa: F401
from app.framework.database import Base, Database
from app.framework.errors import AppError
from app.modules.orders.models import CustomerSnapshot, Fulfillment, Order, OrderItem, Refund
from app.modules.orders.service import OrderService
from app.modules.users.models import User


def _database(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'orders.db'}")
    event.listen(
        database.engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database.engine)
    return database


def _seed(db):
    owner = User(username="merchant-orders", password_hash="hash")
    outsider = User(username="outsider-orders", password_hash="hash")
    db.add_all([owner, outsider])
    db.flush()
    customer = CustomerSnapshot(
        owner_id=owner.id,
        customer_key="customer-001",
        display_name="林女士",
        tier="常购顾客",
        order_count=12,
        refund_count=1,
        lifetime_value_minor=28640,
        captured_at=datetime(2026, 8, 8, 9, 0),
        is_demo=True,
        lineage_json=json.dumps({"displayName": {"provenance": "synthetic"}}),
    )
    db.add(customer)
    db.flush()
    order = Order(
        owner_id=owner.id,
        order_no="NB-20260808-001",
        customer_snapshot_id=customer.id,
        status="delivering",
        total_amount_minor=12860,
        placed_at=datetime(2026, 8, 8, 9, 5),
        is_demo=True,
        lineage_json=json.dumps({"products": {"provenance": "observed"}}),
    )
    hidden = Order(
        owner_id=outsider.id,
        order_no="NB-HIDDEN-001",
        status="paid",
        total_amount_minor=9900,
        is_demo=False,
    )
    db.add_all([order, hidden])
    db.flush()
    db.add_all(
        [
            OrderItem(
                order_id=order.id,
                sku="SKU-BEEF-01",
                product_name="鲜牛肉",
                quantity=1,
                unit_price_minor=6860,
                lineage_json=json.dumps({"productName": {"provenance": "observed"}}),
            ),
            Fulfillment(
                order_id=order.id,
                status="delayed",
                carrier="邻里配送",
                estimated_delivery_at=datetime(2026, 8, 8, 10, 0),
                delivered_at=datetime(2026, 8, 8, 10, 18),
                updated_at=datetime(2026, 8, 8, 10, 18),
                lineage_json=json.dumps({"estimatedDeliveryAt": {"provenance": "synthetic"}}),
            ),
            Refund(
                order_id=order.id,
                status="not_requested",
                amount_minor=0,
                lineage_json=json.dumps({"status": {"provenance": "synthetic"}}),
            ),
        ]
    )
    db.commit()
    return owner, outsider, order


def test_owner_can_read_complete_order_context_with_lineage(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, _, order = _seed(db)

        result = OrderService().detail(db, owner.id, order.order_no)

        assert result["orderNo"] == "NB-20260808-001"
        assert result["amount"] == {"currency": "CNY", "minor": 12860}
        assert result["items"] == [
            {
                "id": result["items"][0]["id"],
                "sku": "SKU-BEEF-01",
                "productId": None,
                "productName": "鲜牛肉",
                "quantity": 1,
                "unitPriceMinor": 6860,
                "lineage": {"productName": {"provenance": "observed"}},
            }
        ]
        assert result["fulfillment"]["delayMinutes"] == 18
        assert result["customer"]["displayName"] == "林女士"
        assert result["refund"]["status"] == "not_requested"
        assert result["provenance"] == "synthetic"


def test_order_lookup_does_not_disclose_another_owner(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, outsider, order = _seed(db)
        service = OrderService()

        with pytest.raises(AppError) as missing:
            service.detail(db, outsider.id, order.order_no)
        with pytest.raises(AppError) as unknown:
            service.detail(db, outsider.id, "does-not-exist")

        assert (missing.value.code, missing.value.status_code) == (
            unknown.value.code,
            unknown.value.status_code,
        ) == ("ORDER_NOT_FOUND", 404)


def test_delivery_delay_is_unavailable_without_both_timestamps(tmp_path):
    database = _database(tmp_path)
    with database.session_factory() as db:
        owner, _, order = _seed(db)
        fulfillment = db.query(Fulfillment).filter_by(order_id=order.id).one()
        fulfillment.delivered_at = None
        db.commit()

        result = OrderService().detail(db, owner.id, order.order_no)

        assert result["fulfillment"]["delayMinutes"] is None
        assert result["fulfillment"]["delayProvenance"] == "unavailable"
