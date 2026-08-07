from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd


UCI_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
DOI = "10.24432/C5CG6D"
ARCHIVE_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
TRANSFORM_VERSION = "uci-online-retail-ii-bounded-v1"


def _gzip_csv(headers: list[str], rows: list[list[str]]) -> bytes:
    target = io.StringIO(newline="")
    writer = csv.writer(target, lineterminator="\n")
    writer.writerow(headers); writer.writerows(rows)
    result = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=result, mtime=0, compresslevel=9) as stream:
        stream.write(target.getvalue().encode("utf-8"))
    return result.getvalue()


def normalize(archive: Path, output: Path) -> dict:
    archive_bytes = archive.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("UCI 归档校验失败；上游内容可能发生漂移")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
        workbook = bundle.read("online_retail_II.xlsx")
    frames = []
    for sheet in ("Year 2009-2010", "Year 2010-2011"):
        frame = pd.read_excel(io.BytesIO(workbook), sheet_name=sheet, nrows=150_000)
        frame["source_sheet"] = sheet
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    data = data.dropna(subset=["Invoice", "StockCode", "Description", "InvoiceDate", "Quantity", "Price", "Country"])
    data["invoice"] = data["Invoice"].astype(str).str.replace(".0", "", regex=False)
    data["cancelled"] = data["invoice"].str.startswith("C") | (data["Quantity"] < 0)
    data = data.sort_values(["InvoiceDate", "source_sheet", "invoice", "StockCode"], kind="stable")
    selected = pd.concat([data[~data.cancelled].head(4500), data[data.cancelled].head(500)], ignore_index=True)
    selected = selected.sort_values(["InvoiceDate", "source_sheet", "invoice", "StockCode"], kind="stable")
    rows: list[list[str]] = []
    for source_row, (_, row) in enumerate(selected.iterrows(), 1):
        customer = "" if pd.isna(row["Customer ID"]) else str(row["Customer ID"]).replace(".0", "")
        customer_key = hashlib.sha256(f"uci-retail-demo-v1|{customer}".encode()).hexdigest()[:16] if customer else ""
        rows.append([
            str(source_row), row["source_sheet"], row["invoice"], str(row["StockCode"]), str(row["Description"]).strip(),
            str(int(row["Quantity"])), pd.Timestamp(row["InvoiceDate"]).isoformat(), format(float(row["Price"]), ".2f"),
            customer_key, str(row["Country"]).strip(), "cancelled" if row["cancelled"] else "completed",
        ])
    payload = _gzip_csv(["source_row_key", "source_sheet", "invoice", "stock_code", "description", "quantity", "invoice_at", "unit_price_gbp", "customer_key", "country", "invoice_status"], rows)
    output.mkdir(parents=True, exist_ok=True)
    asset = output / "uci_online_retail_ii.csv.gz"; asset.write_bytes(payload)
    manifest = {
        "dataset_key": "uci-online-retail-ii", "version": "archive-502-bounded-v1", "title": "UCI Online Retail II bounded offline snapshot",
        "source_kind": "public_research_dataset", "source_uri": f"https://doi.org/{DOI}", "publisher": "UCI Machine Learning Repository",
        "license": "CC BY 4.0", "retrieved_at": "2026-08-07", "encoding": "UTF-8 gzip", "transform_version": TRANSFORM_VERSION,
        "source_sha256": {"online+retail+ii.zip": ARCHIVE_SHA256},
        "schema": {"invoice": "observed", "stock_code": "observed", "description": "observed", "quantity": "observed", "invoice_at": "observed", "unit_price_gbp": "observed", "customer_key": "derived one-way pseudonym", "country": "observed", "invoice_status": "derived from cancellation marker/negative quantity"},
        "limitations": ["仅为固定的 5,000 行分层演示快照，不代表全量分布", "商品描述为英文", "顾客标识已单向脱敏", "取消状态由发票 C 前缀或负数量确定", "不包含客服对话或退款原因"],
        "selection_rules": ["从两个年度工作表各读取前 150,000 行候选", "按交易时间稳定排序", "保留最早 4,500 条非取消明细与最早 500 条取消明细", "缺少核心交易字段的行排除"],
        "counts": {"lines": len(rows), "invoices": len({r[2] for r in rows}), "products": len({r[3] for r in rows}), "countries": len({r[9] for r in rows}), "cancelled_lines": sum(r[10] == "cancelled" for r in rows)},
        "files": [{"path": asset.name, "sha256": hashlib.sha256(payload).hexdigest(), "rows": len(rows)}],
    }
    (output / "uci_online_retail_ii.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="验证并生成 UCI Online Retail II 固定离线快照")
    parser.add_argument("archive", type=Path, help="从 UCI_URL 下载的原始 zip")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "app/modules/demo/assets/retail")
    args = parser.parse_args(); print(json.dumps(normalize(args.archive, args.output), ensure_ascii=False, indent=2))
