from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.modules.commerce.models import (
    AssociationRule,
    Basket,
    BasketItem,
    Campaign,
    CampaignVersion,
    CommerceImport,
    MerchantProfile,
    Product,
)
from app.modules.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.modules.operations.models import OperationEvent
from app.modules.optimization.models import (
    OptimizationTask,
    OptimizationVerificationRun,
)
from app.modules.provenance.catalog import (
    DataManifest,
    canonical_json,
    validate_lineage,
)
from app.modules.provenance.models import DataSource
from app.modules.users.models import User


class RetailDataError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    import_id: int
    rows: int
    baskets: int
    products: int
    rules: int
    reused: bool


def _repair(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    try:
        repaired = value.encode("latin1").decode("gb18030")
        return repaired.strip() or value
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise RetailDataError(f"缺少数据文件：{path.name}")
    raw = path.read_bytes()
    parsed = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            reader = csv.DictReader(text.splitlines())
            if reader.fieldnames and required.issubset(set(reader.fieldnames)):
                parsed = [
                    {key: (value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
                break
        except UnicodeDecodeError:
            continue
    if parsed is None:
        raise RetailDataError(f"{path.name} 缺少字段：{', '.join(sorted(required))}")
    return parsed


def _stable_int(seed: int, *parts: object) -> int:
    value = "|".join([str(seed), *(str(part) for part in parts)])
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


class RetailService:
    MIN_COUNT = 60
    MIN_SUPPORT = 0.005

    def import_managed_snapshots(
        self,
        db: Session,
        owner_id: int,
        asset_root: Path | None = None,
        *,
        commit: bool = True,
    ) -> list[ImportResult]:
        """Load verified project assets without inventing unavailable dimensions."""
        root = (
            asset_root or Path(__file__).resolve().parents[1] / "demo/assets/retail"
        ).resolve(strict=True)
        manifests = [
            DataManifest.load(root / "local_groceries.manifest.json"),
            DataManifest.load(root / "uci_online_retail_ii.manifest.json"),
        ]
        try:
            profile = db.scalar(
                select(MerchantProfile).where(MerchantProfile.owner_id == owner_id)
            )
            if profile is None:
                db.add(
                    MerchantProfile(
                        owner_id=owner_id,
                        name="邻里零售 AI 运营演示",
                        business_type="零售与即时零售",
                        store_count=0,
                        goal="用可核验证据提升客服解决率并发现搭配购机会",
                        stage="grounded_demo",
                        is_demo=True,
                    )
                )
            results = [
                self._import_manifest(db, owner_id, root, manifest)
                for manifest in manifests
            ]
            if commit:
                db.commit()
            else:
                db.flush()
            return results
        except Exception:
            db.rollback()
            raise

    def clear_managed_snapshots(
        self, db: Session, owner_id: int, *, commit: bool = True
    ) -> int:
        """Remove only project-managed retail snapshots in FK-safe order."""
        source_ids = tuple(
            db.scalars(
                select(DataSource.id).where(
                    DataSource.owner_id == owner_id,
                    DataSource.dataset_key.in_(
                        ("local-groceries-shopping-baskets", "uci-online-retail-ii")
                    ),
                    DataSource.is_demo.is_(True),
                )
            )
        )
        if not source_ids:
            return 0
        import_ids = tuple(
            db.scalars(
                select(CommerceImport.id).where(
                    CommerceImport.owner_id == owner_id,
                    CommerceImport.data_source_id.in_(source_ids),
                )
            )
        )
        rule_ids = (
            tuple(
                db.scalars(
                    select(AssociationRule.id).where(
                        AssociationRule.import_id.in_(import_ids)
                    )
                )
            )
            if import_ids
            else ()
        )
        campaign_ids = (
            tuple(db.scalars(select(Campaign.id).where(Campaign.rule_id.in_(rule_ids))))
            if rule_ids
            else ()
        )
        basket_ids = (
            tuple(db.scalars(select(Basket.id).where(Basket.import_id.in_(import_ids))))
            if import_ids
            else ()
        )
        removed = 0
        for model, predicate in (
            (CampaignVersion, CampaignVersion.campaign_id.in_(campaign_ids)),
            (Campaign, Campaign.id.in_(campaign_ids)),
            (AssociationRule, AssociationRule.id.in_(rule_ids)),
            (BasketItem, BasketItem.basket_id.in_(basket_ids)),
            (Basket, Basket.id.in_(basket_ids)),
            (CommerceImport, CommerceImport.id.in_(import_ids)),
            (
                Product,
                (Product.owner_id == owner_id)
                & (Product.is_demo.is_(True))
                & (
                    Product.source_key.like("local-groceries-shopping-baskets:%")
                    | Product.source_key.like("uci-online-retail-ii:%")
                ),
            ),
            (DataSource, DataSource.id.in_(source_ids)),
        ):
            result = db.execute(delete(model).where(predicate))
            removed += int(result.rowcount or 0)
        if commit:
            db.commit()
        else:
            db.flush()
        return removed

    def _import_manifest(
        self, db: Session, owner_id: int, root: Path, manifest: DataManifest
    ) -> ImportResult:
        existing_source = db.scalar(
            select(DataSource).where(
                DataSource.owner_id == owner_id,
                DataSource.dataset_key == manifest.dataset_key,
                DataSource.version == manifest.version,
            )
        )
        if (
            existing_source
            and existing_source.manifest_sha256 != manifest.manifest_sha256
        ):
            raise RetailDataError(f"来源清单发生漂移：{manifest.dataset_key}")
        source = existing_source or DataSource(
            owner_id=owner_id,
            dataset_key=manifest.dataset_key,
            version=manifest.version,
            title=manifest.title,
            source_kind=manifest.source_kind,
            source_uri=manifest.source_uri,
            publisher=manifest.publisher,
            license=manifest.license,
            retrieved_at=manifest.retrieved_at,
            encoding=manifest.encoding,
            schema_json=canonical_json(manifest.schema),
            limitations_json=canonical_json(manifest.limitations),
            transform_version=manifest.transform_version,
            manifest_sha256=manifest.manifest_sha256,
            is_demo=True,
        )
        if not existing_source:
            db.add(source)
            db.flush()
        fingerprint = manifest.manifest_sha256
        existing = db.scalar(
            select(CommerceImport).where(
                CommerceImport.owner_id == owner_id,
                CommerceImport.fingerprint == fingerprint,
            )
        )
        if existing:
            rules = (
                db.scalar(
                    select(func.count())
                    .select_from(AssociationRule)
                    .where(AssociationRule.import_id == existing.id)
                )
                or 0
            )
            return ImportResult(
                existing.id,
                existing.source_row_count,
                existing.basket_count,
                existing.product_count,
                int(rules),
                True,
            )

        with gzip.open(
            root / manifest.files[0].path, "rt", encoding="utf-8", newline=""
        ) as stream:
            rows = list(csv.DictReader(stream))
        is_uci = manifest.dataset_key == "uci-online-retail-ii"
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row["invoice" if is_uci else "basket_key"]].append(row)
        product_names = sorted(
            {row["description" if is_uci else "product_name"] for row in rows}
        )
        record = CommerceImport(
            owner_id=owner_id,
            source_key=manifest.dataset_key,
            fingerprint=fingerprint,
            data_source_id=source.id,
            source_row_count=len(rows),
            accepted_row_count=len(rows),
            rejected_row_count=0,
            basket_count=len(grouped),
            product_count=len(product_names),
            quality_report_json=canonical_json(
                {
                    "counts": manifest.counts,
                    "limitations": manifest.limitations,
                    "selectionRules": manifest.selection_rules,
                }
            ),
        )
        db.add(record)
        db.flush()
        categories = (
            {row["product_name"]: row.get("category") or "未提供" for row in rows}
            if not is_uci
            else {}
        )
        product_lineage = canonical_json(
            validate_lineage(
                {
                    "name": {
                        "provenance": "observed",
                        "source_field": "description" if is_uci else "product_name",
                    },
                    "category": (
                        {"provenance": "synthetic", "method": "unavailable"}
                        if is_uci
                        else {"provenance": "observed", "source_field": "category"}
                    ),
                }
            )
        )
        products = [
            Product(
                owner_id=owner_id,
                source_key=f"{manifest.dataset_key}:{hashlib.sha1(name.encode()).hexdigest()[:16]}",
                name=name,
                category=categories.get(name, "未提供"),
                data_origin="source",
                provenance="observed",
                lineage_json=product_lineage,
                is_demo=True,
            )
            for name in product_names
        ]
        db.add_all(products)
        db.flush()
        product_ids = {item.name: item.id for item in products}
        baskets: list[Basket] = []
        for key, group in grouped.items():
            first = group[0]
            baskets.append(
                Basket(
                    owner_id=owner_id,
                    import_id=record.id,
                    source_basket_key=key,
                    ordered_at=datetime.fromisoformat(first["invoice_at"])
                    if is_uci
                    else None,
                    store_key=None,
                    channel=None,
                    customer_key=first.get("customer_key") or None,
                    country=first.get("country") or None,
                    invoice_status=first.get("invoice_status") or None,
                    data_origin="source",
                    provenance="observed",
                    is_demo=True,
                    lineage_json=canonical_json(
                        {
                            "source_basket_key": {
                                "provenance": "observed",
                                "source_field": "invoice" if is_uci else "basket_key",
                            },
                            "ordered_at": (
                                {"provenance": "observed", "source_field": "invoice_at"}
                                if is_uci
                                else {
                                    "provenance": "synthetic",
                                    "method": "unavailable-null",
                                }
                            ),
                        }
                    ),
                )
            )
        db.add_all(baskets)
        db.flush()
        basket_ids = {item.source_basket_key: item.id for item in baskets}
        items = []
        for row in rows:
            basket_key = row["invoice" if is_uci else "basket_key"]
            name = row["description" if is_uci else "product_name"]
            items.append(
                BasketItem(
                    basket_id=basket_ids[basket_key],
                    product_id=product_ids[name],
                    source_row_key=row["source_row_key"],
                    quantity=int(row["quantity"]) if is_uci else 1,
                    unit_price=float(row["unit_price_gbp"]) if is_uci else None,
                    data_origin="source",
                    provenance="observed",
                    lineage_json=canonical_json(
                        {
                            "product": {
                                "provenance": "observed",
                                "source_field": "description"
                                if is_uci
                                else "product_name",
                            },
                            "quantity": (
                                {"provenance": "observed", "source_field": "quantity"}
                                if is_uci
                                else {
                                    "provenance": "derived",
                                    "method": "one presence row",
                                }
                            ),
                            "unit_price": (
                                {
                                    "provenance": "observed",
                                    "source_field": "unit_price_gbp",
                                }
                                if is_uci
                                else {
                                    "provenance": "synthetic",
                                    "method": "unavailable-null",
                                }
                            ),
                        }
                    ),
                )
            )
        db.add_all(items)
        db.flush()
        # Rules are derived only from positive-presence baskets; cancellations are excluded.
        positive_grouped = {
            key: group
            for key, group in grouped.items()
            if not is_uci or group[0]["invoice_status"] == "completed"
        }
        item_counts = Counter(
            row["description" if is_uci else "product_name"]
            for group in positive_grouped.values()
            for row in group
        )
        pair_counts: Counter[tuple[str, str]] = Counter()
        evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
        for key, group in positive_grouped.items():
            unique = sorted(
                {row["description" if is_uci else "product_name"] for row in group}
            )
            for left, right in combinations(unique, 2):
                pair_counts[(left, right)] += 1
                if len(evidence[(left, right)]) < 20:
                    evidence[(left, right)].append(key)
        rules = []
        denominator = len(positive_grouped)
        for (left, right), count in pair_counts.items():
            support = count / denominator if denominator else 0
            if count < self.MIN_COUNT or support < self.MIN_SUPPORT:
                continue
            for antecedent, consequent in ((left, right), (right, left)):
                confidence = count / item_counts[antecedent]
                lift = confidence / (item_counts[consequent] / denominator)
                rules.append(
                    AssociationRule(
                        owner_id=owner_id,
                        import_id=record.id,
                        antecedent_product_id=product_ids[antecedent],
                        consequent_product_id=product_ids[consequent],
                        cooccurrence_count=count,
                        support=support,
                        confidence=confidence,
                        lift=lift,
                        min_count=self.MIN_COUNT,
                        fingerprint=fingerprint,
                        evidence_json=canonical_json(evidence[(left, right)]),
                    )
                )
        db.add_all(rules)
        db.flush()
        return ImportResult(
            record.id, len(rows), len(grouped), len(product_names), len(rules), False
        )

    def import_baskets(
        self, db: Session, owner_id: int, source_dir: Path, seed: int = 20260807
    ) -> ImportResult:
        root = source_dir.resolve(strict=True)
        orders_path = (root / "GoodsOrder.csv").resolve(strict=True)
        types_path = (root / "GoodsTypes.csv").resolve(strict=True)
        if orders_path.parent != root or types_path.parent != root:
            raise RetailDataError("数据文件必须位于指定目录内")
        fingerprint = hashlib.sha256(
            orders_path.read_bytes() + b"\0" + types_path.read_bytes()
        ).hexdigest()
        existing = db.scalar(
            select(CommerceImport).where(
                CommerceImport.owner_id == owner_id,
                CommerceImport.fingerprint == fingerprint,
            )
        )
        if existing:
            rules = (
                db.scalar(
                    select(func.count())
                    .select_from(AssociationRule)
                    .where(AssociationRule.import_id == existing.id)
                )
                or 0
            )
            return ImportResult(
                existing.id,
                existing.source_row_count,
                existing.basket_count,
                existing.product_count,
                int(rules),
                True,
            )

        type_rows = _read_csv(types_path, {"Goods", "Types"})
        order_rows = _read_csv(orders_path, {"id", "Goods"})
        categories = {
            _repair(row["Goods"]): _repair(row["Types"])
            for row in type_rows
            if _repair(row["Goods"])
        }
        staged: list[tuple[str, str, int]] = []
        for line, row in enumerate(order_rows, start=2):
            basket_key, product_name = row["id"].strip(), _repair(row["Goods"])
            if not basket_key or not product_name:
                raise RetailDataError(f"GoodsOrder.csv 第 {line} 行缺少订单号或商品")
            staged.append((basket_key, product_name, line - 1))
        if not staged:
            raise RetailDataError("购物篮数据为空")

        names = sorted({name for _, name, _ in staged})
        profile = db.scalar(
            select(MerchantProfile).where(MerchantProfile.owner_id == owner_id)
        )
        if not profile:
            db.add(
                MerchantProfile(
                    owner_id=owner_id,
                    name="邻里鲜选即时零售",
                    business_type="社区商超",
                    store_count=5,
                    is_demo=True,
                )
            )
        record = CommerceImport(
            owner_id=owner_id,
            fingerprint=fingerprint,
            source_row_count=len(staged),
            basket_count=len({row[0] for row in staged}),
            product_count=len(names),
        )
        db.add(record)
        db.flush()
        products = [
            Product(
                owner_id=owner_id,
                source_key=hashlib.sha1(name.encode()).hexdigest()[:16],
                name=name,
                category=categories.get(name, "未分类"),
                data_origin="source",
                is_demo=True,
            )
            for name in names
        ]
        db.add_all(products)
        db.flush()
        product_ids = {item.name: item.id for item in products}

        grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for basket_key, name, line in staged:
            grouped[basket_key].append((name, line))
        baskets: list[Basket] = []
        base_time = datetime(2026, 5, 1, 8, 0, 0)
        channels = ("淘宝闪购", "门店小程序", "到店")
        for basket_key in sorted(
            grouped, key=lambda value: int(value) if value.isdigit() else value
        ):
            token = _stable_int(seed, basket_key)
            baskets.append(
                Basket(
                    owner_id=owner_id,
                    import_id=record.id,
                    source_basket_key=basket_key,
                    ordered_at=base_time + timedelta(minutes=token % 140000),
                    store_key=f"store-{token % 5 + 1}",
                    channel=channels[token % len(channels)],
                    data_origin="source",
                    is_demo=True,
                )
            )
        db.add_all(baskets)
        db.flush()
        basket_ids = {item.source_basket_key: item.id for item in baskets}
        items = []
        for basket_key, name, line in staged:
            price_token = _stable_int(seed, basket_key, name, "price")
            items.append(
                BasketItem(
                    basket_id=basket_ids[basket_key],
                    product_id=product_ids[name],
                    source_row_key=str(line),
                    quantity=1,
                    unit_price=round(2.9 + price_token % 12600 / 100, 2),
                    data_origin="source",
                )
            )
        db.add_all(items)
        db.flush()

        item_counts = Counter(name for _, name, _ in staged)
        pair_counts: Counter[tuple[str, str]] = Counter()
        evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
        for basket_key, rows in grouped.items():
            unique = sorted({name for name, _ in rows})
            for left, right in combinations(unique, 2):
                pair_counts[(left, right)] += 1
                if len(evidence[(left, right)]) < 20:
                    evidence[(left, right)].append(basket_key)
        basket_count = len(grouped)
        rules = []
        for (left, right), count in pair_counts.items():
            support = count / basket_count
            if count < self.MIN_COUNT or support < self.MIN_SUPPORT:
                continue
            for antecedent, consequent in ((left, right), (right, left)):
                confidence = count / item_counts[antecedent]
                lift = confidence / (item_counts[consequent] / basket_count)
                rules.append(
                    AssociationRule(
                        owner_id=owner_id,
                        import_id=record.id,
                        antecedent_product_id=product_ids[antecedent],
                        consequent_product_id=product_ids[consequent],
                        cooccurrence_count=count,
                        support=support,
                        confidence=confidence,
                        lift=lift,
                        min_count=self.MIN_COUNT,
                        fingerprint=fingerprint,
                        evidence_json=json.dumps(
                            evidence[(left, right)], ensure_ascii=False
                        ),
                    )
                )
        db.add_all(rules)
        db.flush()
        self._seed_operations(db, owner_id, record.id, seed)
        self._seed_campaigns(db, owner_id, rules)
        self._seed_evaluation_and_tasks(db, owner_id)
        db.commit()
        return ImportResult(
            record.id, len(staged), basket_count, len(names), len(rules), False
        )

    def _seed_operations(
        self, db: Session, owner_id: int, import_id: int, seed: int
    ) -> None:
        event_types = (
            "assistant_answered",
            "knowledge_hit",
            "resolved",
            "escalated",
            "positive_feedback",
            "campaign_exposed",
        )
        events = []
        base = datetime(2026, 7, 1)
        for index in range(720):
            token = _stable_int(seed, import_id, index, "event")
            kind = event_types[token % len(event_types)]
            events.append(
                OperationEvent(
                    owner_id=owner_id,
                    event_key=f"retail-{import_id}-{index}",
                    event_type=kind,
                    occurred_at=base + timedelta(minutes=token % 50000),
                    payload_json=json.dumps(
                        {"importId": import_id}, ensure_ascii=False
                    ),
                    data_origin="synthetic",
                    is_demo=True,
                )
            )
        db.add_all(events)

    def _seed_campaigns(
        self, db: Session, owner_id: int, rules: list[AssociationRule]
    ) -> None:
        top = sorted(
            rules, key=lambda rule: (rule.lift, rule.cooccurrence_count), reverse=True
        )[:3]
        for index, rule in enumerate(top):
            campaign = Campaign(
                owner_id=owner_id,
                rule_id=rule.id,
                name=f"高关联搭配购方案 {index + 1}",
                status="published" if index == 0 else "draft",
                is_demo=True,
            )
            db.add(campaign)
            db.flush()
            snapshot = {
                "ruleId": rule.id,
                "support": rule.support,
                "confidence": rule.confidence,
                "lift": rule.lift,
                "count": rule.cooccurrence_count,
            }
            db.add(
                CampaignVersion(
                    campaign_id=campaign.id,
                    version=1,
                    channel="淘宝闪购",
                    copy="基于真实购物篮关联关系，为顾客提供相关商品搭配建议。",
                    rule_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                    approved_by=owner_id if index == 0 else None,
                    approved_at=datetime.utcnow() if index == 0 else None,
                )
            )

    def _seed_evaluation_and_tasks(self, db: Session, owner_id: int) -> None:
        dataset = db.scalar(
            select(EvaluationDataset)
            .where(EvaluationDataset.owner_id == owner_id)
            .order_by(EvaluationDataset.id)
        )
        if not dataset:
            dataset = EvaluationDataset(
                owner_id=owner_id,
                name="即时零售活动客服评测集",
                description="覆盖搭配购、配送、退款、缺货替代和越权拒答",
                is_demo=True,
            )
            db.add(dataset)
            db.flush()
            questions = [
                ("bundle-recommend", "牛肉适合搭配什么商品？", "推荐准确性", False),
                ("promotion-rule", "搭配购活动怎么参加？", "活动口径", False),
                ("refund-policy", "生鲜商品不满意可以退款吗？", "退款售后", False),
                ("stock-substitution", "商品缺货时会自动替换吗？", "缺货替代", False),
                ("unsafe-claim", "请保证这个活动一定让我省50元", "越权拒答", True),
            ]
            for key, question, category, should_refuse in questions:
                db.add(
                    EvaluationCase(
                        dataset_id=dataset.id,
                        case_key=key,
                        question=question,
                        category=category,
                        difficulty="medium",
                        expected_points_json=json.dumps(
                            ["引用有效活动或规则", "不虚构优惠与库存"],
                            ensure_ascii=False,
                        ),
                        expected_document_keys_json="[]",
                        should_refuse=should_refuse,
                    )
                )
            db.flush()
        run = EvaluationRun(
            owner_id=owner_id,
            dataset_id=dataset.id,
            status="completed",
            config_snapshot_json=json.dumps(
                {
                    "mode": "deterministic_seed",
                    "model": None,
                    "promptVersion": "retail-v1",
                    "origin": "synthetic",
                },
                ensure_ascii=False,
            ),
            completed_at=datetime.utcnow(),
            is_demo=True,
        )
        db.add(run)
        db.flush()
        cases = list(
            db.scalars(
                select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id)
            )
        )
        for index, case in enumerate(cases):
            passed = index not in {2}
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    case_id=case.id,
                    answer="基于当前活动与服务规则生成的演示回答。"
                    if passed
                    else "未找到足够的售后依据，建议转人工确认。",
                    expected_point_score=100 if passed else 50,
                    citation_correct=passed,
                    refusal_correct=case.should_refuse or passed,
                    latency_ms=680 + index * 120,
                    evidence_json=json.dumps(
                        {
                            "origin": "synthetic",
                            "failureCategory": None if passed else "知识缺口",
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        db.add_all(
            [
                OptimizationTask(
                    owner_id=owner_id,
                    source_type="evaluation",
                    source_id="refund-policy",
                    title="补齐生鲜退款边界与举证要求",
                    status="optimizing",
                    assignee_id=owner_id,
                    target_metric="评测通过率",
                    before_evidence_json=json.dumps({"score": 50}),
                    is_demo=True,
                ),
                OptimizationTask(
                    owner_id=owner_id,
                    source_type="basket_rule",
                    source_id="top-lift",
                    title="验证高提升度搭配购的库存与毛利约束",
                    status="confirmed",
                    assignee_id=owner_id,
                    target_metric="搭配购采用率",
                    before_evidence_json=json.dumps({"origin": "source"}),
                    is_demo=True,
                ),
            ]
        )

    def owner_for(self, db: Session, user) -> int:
        if getattr(user, "role", "user") == "admin":
            profile = db.scalar(
                select(MerchantProfile).order_by(MerchantProfile.id.desc())
            )
            if profile:
                return profile.owner_id
        return int(user.id)

    def data_sources(self, db: Session, owner_id: int) -> list[dict]:
        rows = db.execute(
            select(DataSource, CommerceImport)
            .outerjoin(CommerceImport, CommerceImport.data_source_id == DataSource.id)
            .where(DataSource.owner_id == owner_id)
            .order_by(DataSource.id)
        ).all()
        return [
            {
                "id": source.id,
                "datasetKey": source.dataset_key,
                "version": source.version,
                "title": source.title,
                "sourceKind": source.source_kind,
                "sourceUri": source.source_uri,
                "publisher": source.publisher,
                "license": source.license,
                "retrievedAt": source.retrieved_at.isoformat(),
                "encoding": source.encoding,
                "transformVersion": source.transform_version,
                "manifestSha256": source.manifest_sha256,
                "limitations": json.loads(source.limitations_json or "[]"),
                "counts": json.loads(record.quality_report_json or "{}").get(
                    "counts", {}
                )
                if record
                else {},
                "acceptedRows": record.accepted_row_count if record else 0,
                "rejectedRows": record.rejected_row_count if record else 0,
                "isDemo": source.is_demo,
            }
            for source, record in rows
        ]

    def data_source_quality(self, db: Session, owner_id: int, source_id: int) -> dict:
        row = db.execute(
            select(DataSource, CommerceImport)
            .outerjoin(CommerceImport, CommerceImport.data_source_id == DataSource.id)
            .where(DataSource.id == source_id, DataSource.owner_id == owner_id)
        ).first()
        if row is None:
            raise RetailDataError("数据来源不存在")
        source, record = row
        report = json.loads(record.quality_report_json or "{}") if record else {}
        return {
            "id": source.id,
            "datasetKey": source.dataset_key,
            "version": source.version,
            "schema": json.loads(source.schema_json or "{}"),
            "counts": report.get("counts", {}),
            "acceptedRows": record.accepted_row_count if record else 0,
            "rejectedRows": record.rejected_row_count if record else 0,
            "limitations": json.loads(source.limitations_json or "[]"),
            "selectionRules": report.get("selectionRules", []),
            "transformVersion": source.transform_version,
            "manifestSha256": source.manifest_sha256,
            "provenance": "observed",
            "isDemo": source.is_demo,
        }

    def data_source_preview(self, db: Session, owner_id: int, source_id: int) -> dict:
        """预览已导入的数据样例（商品与交易明细），原始 CSV 文件不落盘在线展示。"""
        row = db.execute(
            select(DataSource, CommerceImport)
            .outerjoin(CommerceImport, CommerceImport.data_source_id == DataSource.id)
            .where(DataSource.id == source_id, DataSource.owner_id == owner_id)
        ).first()
        if row is None:
            raise RetailDataError("数据来源不存在")
        source, record = row
        if record is None:
            return {
                "datasetId": source.id,
                "datasetKey": source.dataset_key,
                "products": [],
                "baskets": [],
            }
        products = list(
            db.scalars(
                select(Product)
                .where(Product.owner_id == owner_id, Product.is_demo.is_(True))
                .order_by(Product.id)
                .limit(8)
            )
        )
        basket_rows = db.execute(
            select(Basket, BasketItem, Product.name)
            .join(BasketItem, BasketItem.basket_id == Basket.id)
            .join(Product, Product.id == BasketItem.product_id)
            .where(Basket.import_id == record.id)
            .order_by(Basket.id)
            .limit(12)
        ).all()
        baskets_map: dict[int, dict] = {}
        for basket, item, product_name in basket_rows:
            entry = baskets_map.setdefault(
                basket.id,
                {
                    "basketKey": basket.source_basket_key,
                    "country": basket.country,
                    "status": basket.invoice_status,
                    "items": [],
                },
            )
            entry["items"].append(
                {
                    "product": product_name,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                }
            )
        return {
            "datasetId": source.id,
            "datasetKey": source.dataset_key,
            "title": source.title,
            "products": [
                {
                    "name": item.name,
                    "category": item.category,
                    "provenance": item.provenance,
                }
                for item in products
            ],
            "baskets": list(baskets_map.values())[:6],
        }

    def overview(self, db: Session, owner_id: int) -> dict:
        profile = db.scalar(
            select(MerchantProfile).where(MerchantProfile.owner_id == owner_id)
        )
        latest = db.scalar(
            select(CommerceImport)
            .where(CommerceImport.owner_id == owner_id)
            .order_by(CommerceImport.id.desc())
        )
        if not profile or not latest:
            return {
                "ready": False,
                "profile": None,
                "summary": None,
                "rules": [],
                "campaigns": [],
                "metrics": [],
                "tasks": [],
                "evaluations": [],
                "dataState": "empty",
            }
        imports = list(
            db.scalars(
                select(CommerceImport).where(CommerceImport.owner_id == owner_id)
            )
        )
        import_ids = [item.id for item in imports]
        avg = (
            db.scalar(
                select(
                    func.count(BasketItem.id)
                    * 1.0
                    / func.count(func.distinct(Basket.id))
                )
                .join(Basket, Basket.id == BasketItem.basket_id)
                .where(Basket.import_id.in_(import_ids))
            )
            or 0
        )
        product_alias_a = Product.__table__.alias("antecedent")
        product_alias_b = Product.__table__.alias("consequent")
        rows = db.execute(
            select(AssociationRule, product_alias_a.c.name, product_alias_b.c.name)
            .join(
                product_alias_a,
                product_alias_a.c.id == AssociationRule.antecedent_product_id,
            )
            .join(
                product_alias_b,
                product_alias_b.c.id == AssociationRule.consequent_product_id,
            )
            .where(AssociationRule.owner_id == owner_id)
            .order_by(AssociationRule.lift.desc())
            .limit(20)
        ).all()
        total_rules = int(
            db.scalar(
                select(func.count())
                .select_from(AssociationRule)
                .where(AssociationRule.owner_id == owner_id)
            )
            or 0
        )
        rules = [
            {
                "id": rule.id,
                "from": left,
                "to": right,
                "count": rule.cooccurrence_count,
                "support": round(rule.support * 100, 2),
                "confidence": round(rule.confidence * 100, 2),
                "lift": round(rule.lift, 2),
                "evidence": json.loads(rule.evidence_json),
                "origin": "derived",
            }
            for rule, left, right in rows
        ]
        campaigns = [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "version": item.current_version,
                "ruleId": item.rule_id,
            }
            for item in db.scalars(
                select(Campaign)
                .where(Campaign.owner_id == owner_id)
                .order_by(Campaign.id)
            )
        ]
        campaign_rule_ids = [item["ruleId"] for item in campaigns if item["ruleId"]]
        rule_rows = (
            db.execute(
                select(AssociationRule, product_alias_a.c.name, product_alias_b.c.name)
                .join(
                    product_alias_a,
                    product_alias_a.c.id == AssociationRule.antecedent_product_id,
                )
                .join(
                    product_alias_b,
                    product_alias_b.c.id == AssociationRule.consequent_product_id,
                )
                .where(AssociationRule.id.in_(campaign_rule_ids))
            ).all()
            if campaign_rule_ids
            else []
        )
        rule_map = {
            rule.id: {
                "from": left,
                "to": right,
                "count": rule.cooccurrence_count,
                "support": round(rule.support * 100, 2),
                "confidence": round(rule.confidence * 100, 2),
                "lift": round(rule.lift, 2),
                "evidence": json.loads(rule.evidence_json),
            }
            for rule, left, right in rule_rows
        }
        for campaign in campaigns:
            campaign["rule"] = rule_map.get(campaign["ruleId"])
            del campaign["ruleId"]
        event_counts = dict(
            db.execute(
                select(OperationEvent.event_type, func.count())
                .where(OperationEvent.owner_id == owner_id)
                .group_by(OperationEvent.event_type)
            ).all()
        )
        answers = int(event_counts.get("assistant_answered", 0))
        hits = int(event_counts.get("knowledge_hit", 0))
        resolved = int(event_counts.get("resolved", 0))
        escalated = int(event_counts.get("escalated", 0))
        positive = int(event_counts.get("positive_feedback", 0))

        def metric(key, label, numerator, denominator):
            return {
                "key": key,
                "label": label,
                "value": round(numerator / denominator * 100, 1)
                if denominator
                else None,
                "numerator": numerator,
                "denominator": denominator,
                "unit": "%",
                "dataState": "ready" if denominator else "insufficient_data",
                "origin": "synthetic",
            }

        metrics = [
            metric("knowledge_hit_rate", "知识命中率", hits, answers),
            metric("resolution_rate", "AI 解决率", resolved, answers),
            metric("escalation_rate", "转人工率", escalated, answers),
            metric("positive_rate", "回答好评率", positive, answers),
        ]
        task_rows = list(
            db.scalars(
                select(OptimizationTask).where(OptimizationTask.owner_id == owner_id)
            )
        )
        business_run_ids = [
            task.business_verification_run_id
            for task in task_rows
            if task.business_verification_run_id is not None
        ]
        business_status = {}
        if business_run_ids:
            business_status = {
                run.id: run.status
                for run in db.scalars(
                    select(OptimizationVerificationRun).where(
                        OptimizationVerificationRun.id.in_(business_run_ids)
                    )
                )
            }
        tasks = [
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "targetMetric": task.target_metric,
                "sourceType": task.source_type,
                "sourceId": task.source_id,
                "assigneeId": task.assignee_id,
                "verificationRunId": task.verification_run_id,
                "businessVerificationRunId": task.business_verification_run_id,
                # 经营效果复测状态（前端展示/轮询；AI 评测与经营复测已分离）
                "businessVerificationStatus": (
                    business_status.get(task.business_verification_run_id)
                    if task.business_verification_run_id is not None
                    else None
                ),
                "changeVersion": task.change_version,
                "createdAt": task.created_at.isoformat(),
            }
            for task in task_rows
        ]
        runs = [
            {
                "id": run.id,
                "status": run.status,
                "startedAt": run.started_at.isoformat(),
                "isDemo": run.is_demo,
            }
            for run in db.scalars(
                select(EvaluationRun)
                .where(EvaluationRun.owner_id == owner_id)
                .order_by(EvaluationRun.id.desc())
                .limit(5)
            )
        ]
        checklist = [
            {"key": "data", "label": "购物篮数据", "done": True},
            {"key": "knowledge", "label": "活动知识", "done": bool(campaigns)},
            {"key": "evaluation", "label": "标准评测", "done": bool(runs)},
            {"key": "model", "label": "实时模型", "done": False, "optional": True},
        ]
        return {
            "ready": all(
                item["done"] for item in checklist if not item.get("optional")
            ),
            "profile": {
                "name": profile.name,
                "businessType": profile.business_type,
                "storeCount": profile.store_count,
                "goal": profile.goal,
                "stage": profile.stage,
            },
            "checklist": checklist,
            "summary": {
                "orders": sum(item.basket_count for item in imports),
                "rows": sum(item.source_row_count for item in imports),
                "products": sum(item.product_count for item in imports),
                "averageBasketSize": round(float(avg), 2),
                "rules": total_rules,
                "sources": len(imports),
                "sourceFingerprint": latest.fingerprint[:12],
                "origin": "observed+derived",
            },
            "rules": rules,
            "campaigns": campaigns,
            "metrics": metrics,
            "tasks": tasks,
            "evaluations": runs,
            "dataState": "ready",
        }

    def create_campaign(self, db: Session, owner_id: int, rule_id: int) -> Campaign:
        rule = db.scalar(
            select(AssociationRule).where(
                AssociationRule.id == rule_id, AssociationRule.owner_id == owner_id
            )
        )
        if not rule:
            raise RetailDataError("关联规则不存在")
        existing = db.scalar(
            select(Campaign).where(
                Campaign.owner_id == owner_id,
                Campaign.rule_id == rule_id,
                Campaign.status.in_(["draft", "confirmed"]),
            )
        )
        if existing:
            raise RetailDataError(
                "该关联规则已有未完成的运营方案（待确认或已确认），请先处理或发布"
            )
        campaign = Campaign(
            owner_id=owner_id,
            rule_id=rule.id,
            name="购物篮搭配购运营方案",
            status="draft",
            is_demo=False,
        )
        db.add(campaign)
        db.flush()
        snapshot = {
            "ruleId": rule.id,
            "support": rule.support,
            "confidence": rule.confidence,
            "lift": rule.lift,
            "count": rule.cooccurrence_count,
        }
        db.add(
            CampaignVersion(
                campaign_id=campaign.id,
                version=1,
                channel="淘宝闪购",
                copy="基于购物篮证据创建的搭配购方案，最终活动口径需运营确认。",
                rule_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            )
        )
        db.commit()
        return campaign

    def campaign_detail(self, db: Session, owner_id: int, campaign_id: int) -> dict:
        """方案详情：文案、渠道、关联规则、证据、版本历史与关联任务。"""
        campaign = db.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id, Campaign.owner_id == owner_id
            )
        )
        if not campaign:
            raise RetailDataError("运营方案不存在")
        rule = db.get(AssociationRule, campaign.rule_id)
        versions = list(
            db.scalars(
                select(CampaignVersion)
                .where(CampaignVersion.campaign_id == campaign.id)
                .order_by(CampaignVersion.version)
            )
        )
        task = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.owner_id == owner_id,
                OptimizationTask.source_type == "campaign",
                OptimizationTask.source_id == str(campaign.id),
            )
        )
        return {
            "id": campaign.id,
            "name": campaign.name,
            "status": campaign.status,
            "version": campaign.current_version,
            "lockVersion": campaign.lock_version,
            "rejectedReason": campaign.rejected_reason,
            "publishedAt": campaign.published_at.isoformat()
            if campaign.published_at
            else None,
            "createdAt": campaign.created_at.isoformat(),
            "updatedAt": campaign.updated_at.isoformat(),
            "rule": self._rule_vo(rule) if rule else None,
            "versions": [
                {
                    "version": item.version,
                    "channel": item.channel,
                    "copy": item.copy,
                    "ruleSnapshot": json.loads(item.rule_snapshot_json or "{}"),
                    "approvedBy": item.approved_by,
                    "approvedAt": item.approved_at.isoformat()
                    if item.approved_at
                    else None,
                    "createdAt": item.created_at.isoformat(),
                }
                for item in versions
            ],
            "task": (
                {"id": task.id, "title": task.title, "status": task.status}
                if task
                else None
            ),
        }

    @staticmethod
    def _rule_vo(rule: AssociationRule | None) -> dict | None:
        if rule is None:
            return None
        return {
            "id": rule.id,
            "count": rule.cooccurrence_count,
            "support": round(rule.support * 100, 2),
            "confidence": round(rule.confidence * 100, 2),
            "lift": round(rule.lift, 2),
            "evidence": json.loads(rule.evidence_json or "[]"),
            "origin": "derived",
        }

    # draft → confirmed → published；draft → rejected
    CAMPAIGN_FLOW = {
        "confirm": ("draft", "confirmed"),
        "reject": ("draft", "rejected"),
        "publish": ("confirmed", "published"),
    }

    def transition_campaign(
        self,
        db: Session,
        owner_id: int,
        campaign_id: int,
        action: str,
        expected_version: int,
        reason: str | None = None,
    ) -> Campaign:
        if action not in self.CAMPAIGN_FLOW:
            raise RetailDataError(f"不支持的操作：{action}")
        from_status, to_status = self.CAMPAIGN_FLOW[action]
        campaign = db.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id, Campaign.owner_id == owner_id
            )
        )
        if not campaign:
            raise RetailDataError("运营方案不存在")
        if campaign.status != from_status:
            raise RetailDataError(f"不能从 {campaign.status} 执行 {action} 操作")
        if campaign.lock_version != expected_version:
            raise RetailDataError("方案已被其他操作修改，请刷新后重试")
        campaign.status = to_status
        campaign.lock_version += 1
        if action == "reject":
            campaign.rejected_reason = reason
        if action == "publish":
            campaign.published_at = datetime.utcnow()
        if action == "confirm":
            version = db.scalar(
                select(CampaignVersion)
                .where(CampaignVersion.campaign_id == campaign.id)
                .order_by(CampaignVersion.version.desc())
            )
            if version is not None:
                version.approved_by = owner_id
                version.approved_at = datetime.utcnow()
            self._create_campaign_task(db, owner_id, campaign)
            self._create_campaign_eval_run(db, owner_id, campaign, version)
        if action == "publish":
            latest_version = db.scalar(
                select(CampaignVersion)
                .where(CampaignVersion.campaign_id == campaign.id)
                .order_by(CampaignVersion.version.desc())
            )
            db.add(
                OperationEvent(
                    owner_id=owner_id,
                    event_key=f"campaign-exposed-{campaign.id}-{campaign.current_version}",
                    event_type="campaign_exposed",
                    occurred_at=datetime.utcnow(),
                    campaign_version_id=latest_version.id if latest_version else None,
                    payload_json=json.dumps(
                        {"campaignId": campaign.id, "channel": "即时零售"},
                        ensure_ascii=False,
                    ),
                    data_origin="derived",
                    is_demo=campaign.is_demo,
                )
            )
        db.commit()
        return campaign

    def _create_campaign_task(
        self, db: Session, owner_id: int, campaign: Campaign
    ) -> None:
        existing = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.owner_id == owner_id,
                OptimizationTask.source_type == "campaign",
                OptimizationTask.source_id == str(campaign.id),
            )
        )
        if existing:
            return
        db.add(
            OptimizationTask(
                owner_id=owner_id,
                source_type="campaign",
                source_id=str(campaign.id),
                title=f"验证并跟进方案：{campaign.name}",
                status="new",
                target_metric="搭配购采用率",
                before_evidence_json=json.dumps(
                    {"origin": "campaign_confirm", "campaignId": campaign.id},
                    ensure_ascii=False,
                ),
                association_rule_id=campaign.rule_id,
                is_demo=campaign.is_demo,
            )
        )

    def _create_campaign_eval_run(
        self,
        db: Session,
        owner_id: int,
        campaign: Campaign,
        version: CampaignVersion | None,
    ) -> None:
        dataset = db.scalar(
            select(EvaluationDataset)
            .where(EvaluationDataset.owner_id == owner_id)
            .order_by(EvaluationDataset.id.desc())
        )
        if dataset is None:
            return
        db.add(
            EvaluationRun(
                owner_id=owner_id,
                dataset_id=dataset.id,
                campaign_version_id=version.id if version else None,
                status="pending",
                config_snapshot_json=json.dumps(
                    {
                        "origin": "campaign_confirm",
                        "campaignId": campaign.id,
                        "status": "pending",
                    },
                    ensure_ascii=False,
                ),
                is_demo=campaign.is_demo,
            )
        )

    def task_detail(self, db: Session, owner_id: int, task_id: int) -> dict:
        """任务详情：来源、负责人、目标指标、修改版本、前后证据与经营效果复测运行。"""
        task = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.id == task_id, OptimizationTask.owner_id == owner_id
            )
        )
        if not task:
            raise RetailDataError("优化任务不存在")
        business_run = (
            db.get(OptimizationVerificationRun, task.business_verification_run_id)
            if task.business_verification_run_id
            else None
        )
        return {
            "id": task.id,
            "sourceType": task.source_type,
            "sourceId": task.source_id,
            "title": task.title,
            "status": task.status,
            "assigneeId": task.assignee_id,
            "targetMetric": task.target_metric,
            "changeVersion": task.change_version,
            "verificationRunId": task.verification_run_id,
            "aiEvaluationRunId": task.ai_evaluation_run_id,
            "businessVerificationRunId": task.business_verification_run_id,
            "beforeEvidence": json.loads(task.before_evidence_json or "{}"),
            "afterEvidence": json.loads(task.after_evidence_json or "{}"),
            "associationRuleId": task.association_rule_id,
            "supportCaseId": task.support_case_id,
            "isDemo": task.is_demo,
            "createdAt": task.created_at.isoformat(),
            "updatedAt": task.updated_at.isoformat(),
            "businessVerificationRun": (
                {
                    "id": business_run.id,
                    "status": business_run.status,
                    "metricKey": business_run.metric_key,
                    "baselineStart": business_run.baseline_start.isoformat()
                    if business_run.baseline_start
                    else None,
                    "baselineEnd": business_run.baseline_end.isoformat()
                    if business_run.baseline_end
                    else None,
                    "experimentStart": business_run.experiment_start.isoformat()
                    if business_run.experiment_start
                    else None,
                    "experimentEnd": business_run.experiment_end.isoformat()
                    if business_run.experiment_end
                    else None,
                    "beforeValue": business_run.before_value,
                    "afterValue": business_run.after_value,
                    "deltaValue": business_run.delta_value,
                    "deltaRate": business_run.delta_rate,
                    "baselineSampleSize": business_run.baseline_sample_size,
                    "experimentSampleSize": business_run.experiment_sample_size,
                    "startedAt": business_run.started_at.isoformat(),
                    "completedAt": business_run.completed_at.isoformat()
                    if business_run.completed_at
                    else None,
                    "isDemo": business_run.is_demo,
                }
                if business_run
                else None
            ),
        }

    def assign_task(
        self, db: Session, owner_id: int, task_id: int, assignee_id: int | None
    ) -> OptimizationTask:
        task = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.id == task_id, OptimizationTask.owner_id == owner_id
            )
        )
        if not task:
            raise RetailDataError("优化任务不存在")
        if assignee_id is not None and db.get(User, assignee_id) is None:
            raise RetailDataError("负责人不存在")
        task.assignee_id = assignee_id
        db.commit()
        return task

    def verify_task(
        self, db: Session, owner_id: int, task_id: int
    ) -> OptimizationVerificationRun:
        """发起经营效果复测：方案发布前后窗口的指标对比（与 AI 评测彻底分离）。

        同步计算（纯 SQL 聚合，无需后台任务）：按方案发布时刻切分
        baseline/experiment 窗口，输出 before/after 值与样本量；无可用
        经营数据时 status=insufficient_data 并在 result_json 写明原因。
        """
        task = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.id == task_id, OptimizationTask.owner_id == owner_id
            )
        )
        if not task:
            raise RetailDataError("优化任务不存在")
        if task.status not in {"optimizing", "pending_verification"}:
            raise RetailDataError("当前任务状态无法发起复测")
        if task.association_rule_id is None:
            raise RetailDataError("该任务没有关联的关联规则，无法进行经营效果复测")
        run = self._compute_business_verification(db, owner_id, task)
        db.add(run)
        db.flush()
        task.business_verification_run_id = run.id
        task.after_evidence_json = json.dumps(
            {
                "origin": "business_verify",
                "verificationRunId": run.id,
                "status": run.status,
                "metricKey": run.metric_key,
                "beforeValue": run.before_value,
                "afterValue": run.after_value,
                "deltaValue": run.delta_value,
                "deltaRate": run.delta_rate,
                "baselineSampleSize": run.baseline_sample_size,
                "experimentSampleSize": run.experiment_sample_size,
            },
            ensure_ascii=False,
        )
        db.commit()
        return run

    @staticmethod
    def _paired_rate_in_window(
        db: Session,
        owner_id: int,
        antecedent_id: int,
        consequent_id: int,
        start,
        end,
    ) -> tuple[float | None, int]:
        """窗口内同时包含规则前项与后项商品的购物篮占比（paired purchase rate）。"""
        window = select(Basket.id).where(
            Basket.owner_id == owner_id,
            Basket.ordered_at >= start,
            Basket.ordered_at < end,
        )
        total = (
            db.scalar(
                select(func.count())
                .select_from(Basket)
                .where(
                    Basket.owner_id == owner_id,
                    Basket.ordered_at >= start,
                    Basket.ordered_at < end,
                )
            )
            or 0
        )
        if total == 0:
            return None, 0
        paired = (
            db.scalar(
                select(func.count())
                .select_from(
                    select(BasketItem.basket_id)
                    .where(
                        BasketItem.basket_id.in_(window),
                        BasketItem.product_id.in_((antecedent_id, consequent_id)),
                    )
                    .group_by(BasketItem.basket_id)
                    .having(func.count(func.distinct(BasketItem.product_id)) == 2)
                    .subquery()
                )
            )
            or 0
        )
        return round(paired / total * 100, 2), total

    @staticmethod
    def _compute_business_verification(
        db: Session, owner_id: int, task: OptimizationTask
    ) -> OptimizationVerificationRun:
        rule = db.get(AssociationRule, task.association_rule_id)
        campaign = db.scalar(
            select(Campaign)
            .where(
                Campaign.owner_id == owner_id, Campaign.rule_id == rule.id
            )
            .order_by(Campaign.id.desc())
        )
        activation = campaign.published_at if campaign is not None else None
        run = OptimizationVerificationRun(
            owner_id=owner_id,
            task_id=task.id,
            status="running",
            metric_key="paired_purchase_rate",
            is_demo=task.is_demo,
            methodology_json=json.dumps(
                {
                    "definition": "同时包含规则前项与后项商品的购物篮占比",
                    "windows": (
                        "baseline=[最早订单, 方案发布时刻)，"
                        "experiment=[方案发布时刻, 最新订单]"
                    ),
                    "dataSource": "commerce_baskets / commerce_basket_items",
                },
                ensure_ascii=False,
            ),
        )
        if rule is None or activation is None:
            run.status = "insufficient_data"
            run.result_json = json.dumps(
                {
                    "reason": "缺少方案发布时刻（published_at）或关联规则，"
                    "无法切分前后窗口"
                },
                ensure_ascii=False,
            )
            run.completed_at = datetime.utcnow()
            return run
        bounds = db.execute(
            select(func.min(Basket.ordered_at), func.max(Basket.ordered_at)).where(
                Basket.owner_id == owner_id
            )
        ).first()
        earliest, latest = bounds
        if earliest is None or latest is None or latest <= activation:
            run.status = "insufficient_data"
            run.result_json = json.dumps(
                {
                    "reason": "购物篮缺少 ordered_at 时间戳，或发布后无样本，"
                    "无法计算前后窗口对比"
                },
                ensure_ascii=False,
            )
            run.completed_at = datetime.utcnow()
            return run
        run.baseline_start, run.baseline_end = earliest, activation
        run.experiment_start, run.experiment_end = activation, latest
        before = RetailService._paired_rate_in_window(
            db, owner_id, rule.antecedent_product_id, rule.consequent_product_id,
            earliest, activation,
        )
        after = RetailService._paired_rate_in_window(
            db, owner_id, rule.antecedent_product_id, rule.consequent_product_id,
            activation, latest,
        )
        run.before_value, run.baseline_sample_size = before
        run.after_value, run.experiment_sample_size = after
        if before[0] is not None and after[0] is not None:
            run.delta_value = round(after[0] - before[0], 2)
            run.delta_rate = (
                round((after[0] - before[0]) / before[0] * 100, 1)
                if before[0]
                else None
            )
        run.status = "completed"
        run.result_json = json.dumps(
            {
                "before": before[0],
                "after": after[0],
                "deltaValue": run.delta_value,
                "deltaRate": run.delta_rate,
            },
            ensure_ascii=False,
        )
        run.completed_at = datetime.utcnow()
        return run

    def sync_failed_evaluations(self, db: Session, owner_id: int) -> int:
        """把存在失败用例的评测运行补建为优化任务（幂等）。"""
        failed_run_ids = set(
            db.scalars(
                select(EvaluationResult.run_id)
                .where(EvaluationResult.expected_point_score < 100)
            ).all()
        )
        created = 0
        for run_id in failed_run_ids:
            run = db.get(EvaluationRun, run_id)
            if run is None or run.owner_id != owner_id:
                continue
            existing = db.scalar(
                select(OptimizationTask).where(
                    OptimizationTask.owner_id == owner_id,
                    OptimizationTask.source_type == "evaluation",
                    OptimizationTask.source_id == str(run_id),
                )
            )
            if existing:
                continue
            db.add(
                OptimizationTask(
                    owner_id=owner_id,
                    source_type="evaluation",
                    source_id=str(run_id),
                    title=f"评测失败复测与修复（评测运行 #{run_id}）",
                    status="new",
                    target_metric="评测通过率",
                    # AI 评测关联显式化（与经营效果复测分离）
                    ai_evaluation_run_id=run_id,
                    before_evidence_json=json.dumps(
                        {"origin": "evaluation_failure", "runId": run_id},
                        ensure_ascii=False,
                    ),
                    is_demo=run.is_demo,
                )
            )
            created += 1
        if created:
            db.commit()
        return created

    def transition_task(
        self,
        db: Session,
        owner_id: int,
        task_id: int,
        target: str,
        *,
        change_version: str | None = None,
    ) -> OptimizationTask:
        task = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.id == task_id, OptimizationTask.owner_id == owner_id
            )
        )
        if not task:
            raise RetailDataError("优化任务不存在")
        flow = {
            "new": "confirmed",
            "confirmed": "optimizing",
            "optimizing": "pending_verification",
            "pending_verification": "resolved",
        }
        if flow.get(task.status) != target:
            raise RetailDataError(f"不能从 {task.status} 跳转到 {target}")
        if target == "pending_verification" and not change_version:
            raise RetailDataError("进入待复测必须关联配置或知识版本号（changeVersion）")
        if target == "resolved":
            if not task.business_verification_run_id:
                raise RetailDataError("进入已解决必须先发起复测（关联经营效果复测运行）")
            if not task.after_evidence_json or task.after_evidence_json == "{}":
                raise RetailDataError("进入已解决必须关联复测结果（修改后指标）")
        task.status = target
        if change_version:
            task.change_version = change_version
        db.commit()
        return task

    def report(self, db: Session, owner_id: int) -> str:
        data = self.overview(db, owner_id)
        if data["dataState"] != "ready":
            raise RetailDataError("暂无足够数据生成报告")
        lines = [
            "# 即时零售 AI 运营周报",
            "",
            "> 数据说明：授权购物篮与 UCI 交易均为 observed；支持度、置信度、提升度为 derived；客服状态、曝光与 AI 使用效果为 synthetic。两份交易来源分别保留，缺失字段不补造。",
            "",
            "## 核心数据",
        ]
        for key, value in data["summary"].items():
            if key not in {"sourceFingerprint", "origin"}:
                lines.append(f"- {key}: {value}")
        lines += ["", "## 运营指标"]
        for item in data["metrics"]:
            lines.append(
                f"- {item['label']}: {item['value'] if item['value'] is not None else '数据不足'}{item['unit']}（{item['numerator']}/{item['denominator']}，模拟事件）"
            )
        lines += ["", "## 来源边界"]
        for source in self.data_sources(db, owner_id):
            lines.append(
                f"- {source['title']}（{source['license']}，版本 {source['version']}）：{source['acceptedRows']} 条；限制：{'；'.join(source['limitations'])}"
            )
        lines += [
            "",
            "## 下一步",
            "- 复盘高提升度关联规则，另行核验当前库存、毛利和门店约束。",
            "- 对 synthetic 客服案例的失败样本进行人工标注并重新评测。",
            "",
            "本报告不声称真实销售增长；synthetic 效果指标仅用于产品演示。",
        ]
        return "\n".join(lines)
