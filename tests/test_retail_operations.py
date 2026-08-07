from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import event

import app.application_core  # noqa: F401 - register all mapped tables
from app.framework.database import Base, Database
from app.modules.commerce.service import RetailDataError, RetailService, _repair
from app.modules.users.models import User


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'retail.db'}")
    event.listen(database.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(database.engine)
    return database


def _source(root: Path) -> None:
    root.mkdir()
    with (root / "GoodsTypes.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Goods", "Types"]); writer.writeheader()
        for name, category in (("牛肉", "肉类"), ("根茎类蔬菜", "果蔬"), ("全脂牛奶", "乳制品")):
            writer.writerow({"Goods": name, "Types": category})
    with (root / "GoodsOrder.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "Goods"]); writer.writeheader()
        for basket in range(1, 81):
            writer.writerow({"id": basket, "Goods": "牛肉"})
            writer.writerow({"id": basket, "Goods": "根茎类蔬菜"})
            if basket <= 20:
                writer.writerow({"id": basket, "Goods": "全脂牛奶"})


def test_import_is_idempotent_and_rules_are_evidence_backed(tmp_path: Path):
    database = _database(tmp_path); source = tmp_path / "source"; _source(source)
    try:
        with database.session_factory() as db:
            user = User(username="retail-owner", password_hash="hash", role="admin", is_demo=True); db.add(user); db.commit()
            first = RetailService().import_baskets(db, user.id, source)
            second = RetailService().import_baskets(db, user.id, source)
            overview = RetailService().overview(db, user.id)
        assert (first.rows, first.baskets, first.products) == (180, 80, 3)
        assert first.rules >= 2
        assert second.reused is True
        assert overview["summary"]["orders"] == 80
        assert overview["rules"][0]["evidence"]
        beef_rule = next(rule for rule in overview["rules"] if rule["from"] == "牛肉" and rule["to"] == "根茎类蔬菜")
        assert beef_rule["support"] == 100.0
        assert beef_rule["confidence"] == 100.0
        assert beef_rule["lift"] == 1.0
    finally:
        database.engine.dispose()


def test_import_rejects_missing_columns_atomically(tmp_path: Path):
    database = _database(tmp_path); source = tmp_path / "invalid"; source.mkdir()
    (source / "GoodsOrder.csv").write_text("wrong,value\n1,x\n", encoding="utf-8")
    (source / "GoodsTypes.csv").write_text("Goods,Types\nx,y\n", encoding="utf-8")
    try:
        with database.session_factory() as db:
            user = User(username="owner", password_hash="hash"); db.add(user); db.commit()
            try:
                RetailService().import_baskets(db, user.id, source)
            except RetailDataError as exc:
                assert "缺少字段" in str(exc)
            else:
                raise AssertionError("invalid source was accepted")
            assert RetailService().overview(db, user.id)["dataState"] == "empty"
    finally:
        database.engine.dispose()


def test_known_mojibake_is_repaired():
    assert _repair("È«Ö¬Å£ÄÌ") == "全脂牛奶"
