from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path


TRANSFORM_VERSION = "local-groceries-v1"


def _read(path: Path, required: set[str]) -> tuple[list[dict[str, str]], str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            reader = csv.DictReader(raw.decode(encoding).splitlines())
            rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
            if reader.fieldnames and required.issubset(reader.fieldnames):
                return rows, hashlib.sha256(raw).hexdigest()
        except UnicodeDecodeError:
            pass
    raise ValueError(f"{path.name} 编码或字段不符合预期")


def _gzip_csv(headers: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    raw = buffer.getvalue().encode("utf-8")
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9) as stream:
        stream.write(raw)
    return output.getvalue()


def normalize(source: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    orders_path = (source / "GoodsOrder.csv").resolve(strict=True)
    types_path = (source / "GoodsTypes.csv").resolve(strict=True)
    if orders_path.parent != source or types_path.parent != source:
        raise ValueError("源文件必须直接位于指定只读目录")
    orders, order_hash = _read(orders_path, {"id", "Goods"})
    types, type_hash = _read(types_path, {"Goods", "Types"})
    categories = {row["Goods"]: row["Types"] for row in types if row["Goods"]}
    normalized = []
    for index, row in enumerate(orders, 1):
        basket, product = row["id"], row["Goods"]
        if not basket or not product:
            raise ValueError(f"GoodsOrder.csv 第 {index + 1} 行缺少订单号或商品")
        # 分类表没有覆盖的商品保持空值，不能为了凑齐展示而补造分类。
        normalized.append([str(index), basket, product, categories.get(product, "")])
    normalized.sort(key=lambda row: (int(row[1]) if row[1].isdigit() else row[1], int(row[0])))
    payload = _gzip_csv(["source_row_key", "basket_key", "product_name", "category"], normalized)
    output.mkdir(parents=True, exist_ok=True)
    asset = output / "local_groceries.csv.gz"
    asset.write_bytes(payload)
    manifest = {
        "dataset_key": "local-groceries-shopping-baskets", "version": "2026-08-05-v1",
        "title": "商品零售购物篮分析（匿名交易篮）", "source_kind": "user_authorized_local",
        "source_uri": "user-authorized-local://GoodsOrder.csv+GoodsTypes.csv",
        "publisher": "用户提供的教学案例数据包", "license": "仅限本项目演示；不得再分发原始文件",
        "retrieved_at": "2026-08-07", "encoding": "UTF-8 gzip（源文件 GB18030）",
        "transform_version": TRANSFORM_VERSION,
        "source_sha256": {"GoodsOrder.csv": order_hash, "GoodsTypes.csv": type_hash},
        "schema": {"source_row_key": "observed row number", "basket_key": "observed anonymized basket id", "product_name": "observed", "category": "observed mapping when available"},
        "limitations": ["不包含订单时间", "不包含价格和金额", "不包含顾客身份", "不包含门店、渠道和履约", "每行只表示商品出现在购物篮中", "分类映射缺少 1 个商品（保管产品），该分类保持空值"],
        "selection_rules": ["保留全部有效购物篮明细", "按购物篮编号和原始行号确定性排序", "不补造源数据不存在的字段"],
        "counts": {"baskets": len({row[1] for row in normalized}), "lines": len(normalized), "products": len({row[2] for row in normalized}), "categories": len({row[3] for row in normalized if row[3]})},
        "files": [{"path": asset.name, "sha256": hashlib.sha256(payload).hexdigest(), "rows": len(normalized)}],
    }
    (output / "local_groceries.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将授权的 GBK 购物篮源文件规范化为项目内离线快照")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "app/modules/demo/assets/retail")
    args = parser.parse_args()
    print(json.dumps(normalize(args.source, args.output), ensure_ascii=False, indent=2))
