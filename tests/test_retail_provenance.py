from __future__ import annotations

import json
import csv
import gzip
from pathlib import Path

import pytest

from app.modules.provenance.catalog import DataManifest, ProvenanceError, assert_same_owner, validate_lineage
from app.modules.commerce.models import Basket, BasketItem, CommerceImport
from app.modules.commerce.service import RetailService
from app.modules.users.models import User
from sqlalchemy import select
from app.framework.database import Database
from app.framework.migrations import upgrade_database


ASSET_ROOT = Path(__file__).parents[1] / "app/modules/demo/assets/retail"


def test_local_basket_manifest_has_verified_gbk_counts_and_checksum():
    manifest = DataManifest.load(ASSET_ROOT / "local_groceries.manifest.json")
    assert manifest.counts == {"baskets": 9835, "lines": 43367, "products": 169, "categories": 10}
    assert "GB18030" in manifest.encoding
    assert len(manifest.source_sha256) == 2


def test_manifest_rejects_snapshot_checksum_drift(tmp_path: Path):
    manifest_path = ASSET_ROOT / "local_groceries.manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["files"][0]["path"] = "changed.csv.gz"
    (tmp_path / "changed.csv.gz").write_bytes(b"changed")
    (tmp_path / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ProvenanceError, match="校验失败"):
        DataManifest.load(tmp_path / "manifest.json")


def test_lineage_rejects_false_provenance_and_cross_owner_links():
    assert validate_lineage({"product": {"provenance": "observed", "source_field": "product_name"}})
    with pytest.raises(ProvenanceError):
        validate_lineage({"price": {"provenance": "observed"}})
    with pytest.raises(ProvenanceError):
        validate_lineage({"price": {"provenance": "synthetic", "source_field": "unit_price"}})
    with pytest.raises(ProvenanceError, match="同一商家"):
        assert_same_owner(1, 2)


def test_uci_snapshot_has_license_observed_cancellations_and_offline_checksum():
    manifest = DataManifest.load(ASSET_ROOT / "uci_online_retail_ii.manifest.json")
    assert manifest.license == "CC BY 4.0"
    assert manifest.source_uri == "https://doi.org/10.24432/C5CG6D"
    assert manifest.counts["lines"] == 5000
    assert manifest.counts["cancelled_lines"] == 500
    with gzip.open(ASSET_ROOT / manifest.files[0].path, "rt", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    cancelled = [row for row in rows if row["invoice_status"] == "cancelled"]
    assert cancelled and all(row["quantity"].startswith("-") or row["invoice"].startswith("C") for row in cancelled)
    assert all(row["invoice_at"] and row["country"] and row["unit_price_gbp"] for row in rows)


def test_managed_import_is_idempotent_and_preserves_unavailable_dimensions(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'provenance.db'}")
    upgrade_database(database)
    with database.session_factory() as db:
        user = User(username="provenance-owner", password_hash="x", role="user")
        db.add(user); db.commit()
        first = RetailService().import_managed_snapshots(db, user.id)
        second = RetailService().import_managed_snapshots(db, user.id)
        assert [item.reused for item in first] == [False, False]
        assert [item.reused for item in second] == [True, True]
        imports = list(db.scalars(select(CommerceImport).where(CommerceImport.owner_id == user.id)))
        assert sum(item.source_row_count for item in imports) == 48367
        local_basket = db.scalar(select(Basket).where(Basket.import_id == first[0].import_id))
        local_item = db.scalar(select(BasketItem).where(BasketItem.basket_id == local_basket.id))
        assert local_basket.ordered_at is None and local_basket.store_key is None and local_basket.channel is None
        assert local_item.unit_price is None
