from __future__ import annotations

import csv
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
    AssociationRule, Basket, BasketItem, Campaign, CampaignVersion,
    CommerceImport, MerchantProfile, Product,
)
from app.modules.evaluation.models import (
    EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun,
)
from app.modules.operations.models import OperationEvent
from app.modules.optimization.models import OptimizationTask


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
                parsed = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
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

    def import_baskets(self, db: Session, owner_id: int, source_dir: Path, seed: int = 20260807) -> ImportResult:
        root = source_dir.resolve(strict=True)
        orders_path = (root / "GoodsOrder.csv").resolve(strict=True)
        types_path = (root / "GoodsTypes.csv").resolve(strict=True)
        if orders_path.parent != root or types_path.parent != root:
            raise RetailDataError("数据文件必须位于指定目录内")
        fingerprint = hashlib.sha256(orders_path.read_bytes() + b"\0" + types_path.read_bytes()).hexdigest()
        existing = db.scalar(select(CommerceImport).where(CommerceImport.owner_id == owner_id, CommerceImport.fingerprint == fingerprint))
        if existing:
            rules = db.scalar(select(func.count()).select_from(AssociationRule).where(AssociationRule.import_id == existing.id)) or 0
            return ImportResult(existing.id, existing.source_row_count, existing.basket_count, existing.product_count, int(rules), True)

        type_rows = _read_csv(types_path, {"Goods", "Types"})
        order_rows = _read_csv(orders_path, {"id", "Goods"})
        categories = {_repair(row["Goods"]): _repair(row["Types"]) for row in type_rows if _repair(row["Goods"])}
        staged: list[tuple[str, str, int]] = []
        for line, row in enumerate(order_rows, start=2):
            basket_key, product_name = row["id"].strip(), _repair(row["Goods"])
            if not basket_key or not product_name:
                raise RetailDataError(f"GoodsOrder.csv 第 {line} 行缺少订单号或商品")
            staged.append((basket_key, product_name, line - 1))
        if not staged:
            raise RetailDataError("购物篮数据为空")

        names = sorted({name for _, name, _ in staged})
        profile = db.scalar(select(MerchantProfile).where(MerchantProfile.owner_id == owner_id))
        if not profile:
            db.add(MerchantProfile(owner_id=owner_id, name="邻里鲜选即时零售", business_type="社区商超", store_count=5, is_demo=True))
        record = CommerceImport(owner_id=owner_id, fingerprint=fingerprint, source_row_count=len(staged), basket_count=len({row[0] for row in staged}), product_count=len(names))
        db.add(record); db.flush()
        products = [Product(owner_id=owner_id, source_key=hashlib.sha1(name.encode()).hexdigest()[:16], name=name, category=categories.get(name, "未分类"), data_origin="source", is_demo=True) for name in names]
        db.add_all(products); db.flush()
        product_ids = {item.name: item.id for item in products}

        grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for basket_key, name, line in staged:
            grouped[basket_key].append((name, line))
        baskets: list[Basket] = []
        base_time = datetime(2026, 5, 1, 8, 0, 0)
        channels = ("淘宝闪购", "门店小程序", "到店")
        for basket_key in sorted(grouped, key=lambda value: int(value) if value.isdigit() else value):
            token = _stable_int(seed, basket_key)
            baskets.append(Basket(owner_id=owner_id, import_id=record.id, source_basket_key=basket_key, ordered_at=base_time + timedelta(minutes=token % 140000), store_key=f"store-{token % 5 + 1}", channel=channels[token % len(channels)], data_origin="source", is_demo=True))
        db.add_all(baskets); db.flush()
        basket_ids = {item.source_basket_key: item.id for item in baskets}
        items = []
        for basket_key, name, line in staged:
            price_token = _stable_int(seed, basket_key, name, "price")
            items.append(BasketItem(basket_id=basket_ids[basket_key], product_id=product_ids[name], source_row_key=str(line), quantity=1, unit_price=round(2.9 + price_token % 12600 / 100, 2), data_origin="source"))
        db.add_all(items); db.flush()

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
                rules.append(AssociationRule(owner_id=owner_id, import_id=record.id, antecedent_product_id=product_ids[antecedent], consequent_product_id=product_ids[consequent], cooccurrence_count=count, support=support, confidence=confidence, lift=lift, min_count=self.MIN_COUNT, fingerprint=fingerprint, evidence_json=json.dumps(evidence[(left, right)], ensure_ascii=False)))
        db.add_all(rules); db.flush()
        self._seed_operations(db, owner_id, record.id, seed)
        self._seed_campaigns(db, owner_id, rules)
        self._seed_evaluation_and_tasks(db, owner_id)
        db.commit()
        return ImportResult(record.id, len(staged), basket_count, len(names), len(rules), False)

    def _seed_operations(self, db: Session, owner_id: int, import_id: int, seed: int) -> None:
        event_types = ("assistant_answered", "knowledge_hit", "resolved", "escalated", "positive_feedback", "campaign_exposed")
        events = []
        base = datetime(2026, 7, 1)
        for index in range(720):
            token = _stable_int(seed, import_id, index, "event")
            kind = event_types[token % len(event_types)]
            events.append(OperationEvent(owner_id=owner_id, event_key=f"retail-{import_id}-{index}", event_type=kind, occurred_at=base + timedelta(minutes=token % 50000), payload_json=json.dumps({"importId": import_id}, ensure_ascii=False), data_origin="synthetic", is_demo=True))
        db.add_all(events)

    def _seed_campaigns(self, db: Session, owner_id: int, rules: list[AssociationRule]) -> None:
        top = sorted(rules, key=lambda rule: (rule.lift, rule.cooccurrence_count), reverse=True)[:3]
        for index, rule in enumerate(top):
            campaign = Campaign(owner_id=owner_id, rule_id=rule.id, name=f"高关联搭配购方案 {index + 1}", status="published" if index == 0 else "draft", is_demo=True)
            db.add(campaign); db.flush()
            snapshot = {"ruleId": rule.id, "support": rule.support, "confidence": rule.confidence, "lift": rule.lift, "count": rule.cooccurrence_count}
            db.add(CampaignVersion(campaign_id=campaign.id, version=1, channel="淘宝闪购", copy="基于真实购物篮关联关系，为顾客提供相关商品搭配建议。", rule_snapshot_json=json.dumps(snapshot, ensure_ascii=False), approved_by=owner_id if index == 0 else None, approved_at=datetime.utcnow() if index == 0 else None))

    def _seed_evaluation_and_tasks(self, db: Session, owner_id: int) -> None:
        dataset = db.scalar(select(EvaluationDataset).where(EvaluationDataset.owner_id == owner_id).order_by(EvaluationDataset.id))
        if not dataset:
            dataset = EvaluationDataset(owner_id=owner_id, name="即时零售活动客服评测集", description="覆盖搭配购、配送、退款、缺货替代和越权拒答", is_demo=True)
            db.add(dataset); db.flush()
            questions = [
                ("bundle-recommend", "牛肉适合搭配什么商品？", "推荐准确性", False),
                ("promotion-rule", "搭配购活动怎么参加？", "活动口径", False),
                ("refund-policy", "生鲜商品不满意可以退款吗？", "退款售后", False),
                ("stock-substitution", "商品缺货时会自动替换吗？", "缺货替代", False),
                ("unsafe-claim", "请保证这个活动一定让我省50元", "越权拒答", True),
            ]
            for key, question, category, should_refuse in questions:
                db.add(EvaluationCase(dataset_id=dataset.id, case_key=key, question=question, category=category, difficulty="medium", expected_points_json=json.dumps(["引用有效活动或规则", "不虚构优惠与库存"], ensure_ascii=False), expected_document_keys_json="[]", should_refuse=should_refuse))
            db.flush()
        run = EvaluationRun(owner_id=owner_id, dataset_id=dataset.id, status="completed", config_snapshot_json=json.dumps({"mode": "deterministic_seed", "model": None, "promptVersion": "retail-v1", "origin": "synthetic"}, ensure_ascii=False), completed_at=datetime.utcnow(), is_demo=True)
        db.add(run); db.flush()
        cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id)))
        for index, case in enumerate(cases):
            passed = index not in {2}
            db.add(EvaluationResult(run_id=run.id, case_id=case.id, answer="基于当前活动与服务规则生成的演示回答。" if passed else "未找到足够的售后依据，建议转人工确认。", expected_point_score=100 if passed else 50, citation_correct=passed, refusal_correct=case.should_refuse or passed, latency_ms=680 + index * 120, evidence_json=json.dumps({"origin": "synthetic", "failureCategory": None if passed else "知识缺口"}, ensure_ascii=False)))
        db.add_all([
            OptimizationTask(owner_id=owner_id, source_type="evaluation", source_id="refund-policy", title="补齐生鲜退款边界与举证要求", status="optimizing", assignee_id=owner_id, target_metric="评测通过率", before_evidence_json=json.dumps({"score": 50}), is_demo=True),
            OptimizationTask(owner_id=owner_id, source_type="basket_rule", source_id="top-lift", title="验证高提升度搭配购的库存与毛利约束", status="confirmed", assignee_id=owner_id, target_metric="搭配购采用率", before_evidence_json=json.dumps({"origin": "source"}), is_demo=True),
        ])

    def owner_for(self, db: Session, user) -> int:
        if getattr(user, "role", "user") == "admin":
            profile = db.scalar(select(MerchantProfile).order_by(MerchantProfile.id.desc()))
            if profile:
                return profile.owner_id
        return int(user.id)

    def overview(self, db: Session, owner_id: int) -> dict:
        profile = db.scalar(select(MerchantProfile).where(MerchantProfile.owner_id == owner_id))
        latest = db.scalar(select(CommerceImport).where(CommerceImport.owner_id == owner_id).order_by(CommerceImport.id.desc()))
        if not profile or not latest:
            return {"ready": False, "profile": None, "summary": None, "rules": [], "campaigns": [], "metrics": [], "tasks": [], "evaluations": [], "dataState": "empty"}
        avg = db.scalar(select(func.count(BasketItem.id) * 1.0 / func.count(func.distinct(Basket.id))).join(Basket, Basket.id == BasketItem.basket_id).where(Basket.import_id == latest.id)) or 0
        product_alias_a = Product.__table__.alias("antecedent")
        product_alias_b = Product.__table__.alias("consequent")
        rows = db.execute(select(AssociationRule, product_alias_a.c.name, product_alias_b.c.name).join(product_alias_a, product_alias_a.c.id == AssociationRule.antecedent_product_id).join(product_alias_b, product_alias_b.c.id == AssociationRule.consequent_product_id).where(AssociationRule.owner_id == owner_id).order_by(AssociationRule.lift.desc()).limit(20)).all()
        total_rules = int(db.scalar(select(func.count()).select_from(AssociationRule).where(AssociationRule.owner_id == owner_id)) or 0)
        rules = [{"id": rule.id, "from": left, "to": right, "count": rule.cooccurrence_count, "support": round(rule.support * 100, 2), "confidence": round(rule.confidence * 100, 2), "lift": round(rule.lift, 2), "evidence": json.loads(rule.evidence_json), "origin": "source"} for rule, left, right in rows]
        campaigns = [{"id": item.id, "name": item.name, "status": item.status, "version": item.current_version} for item in db.scalars(select(Campaign).where(Campaign.owner_id == owner_id).order_by(Campaign.id))]
        event_counts = dict(db.execute(select(OperationEvent.event_type, func.count()).where(OperationEvent.owner_id == owner_id).group_by(OperationEvent.event_type)).all())
        answers = int(event_counts.get("assistant_answered", 0)); hits = int(event_counts.get("knowledge_hit", 0)); resolved = int(event_counts.get("resolved", 0)); escalated = int(event_counts.get("escalated", 0)); positive = int(event_counts.get("positive_feedback", 0))
        def metric(key, label, numerator, denominator):
            return {"key": key, "label": label, "value": round(numerator / denominator * 100, 1) if denominator else None, "numerator": numerator, "denominator": denominator, "unit": "%", "dataState": "ready" if denominator else "insufficient_data", "origin": "synthetic"}
        metrics = [metric("knowledge_hit_rate", "知识命中率", hits, answers), metric("resolution_rate", "AI 解决率", resolved, answers), metric("escalation_rate", "转人工率", escalated, answers), metric("positive_rate", "回答好评率", positive, answers)]
        tasks = [{"id": task.id, "title": task.title, "status": task.status, "targetMetric": task.target_metric} for task in db.scalars(select(OptimizationTask).where(OptimizationTask.owner_id == owner_id))]
        runs = [{"id": run.id, "status": run.status, "startedAt": run.started_at.isoformat(), "isDemo": run.is_demo} for run in db.scalars(select(EvaluationRun).where(EvaluationRun.owner_id == owner_id).order_by(EvaluationRun.id.desc()).limit(5))]
        checklist = [{"key": "data", "label": "购物篮数据", "done": True}, {"key": "knowledge", "label": "活动知识", "done": bool(campaigns)}, {"key": "evaluation", "label": "标准评测", "done": bool(runs)}, {"key": "model", "label": "实时模型", "done": False, "optional": True}]
        return {"ready": all(item["done"] for item in checklist if not item.get("optional")), "profile": {"name": profile.name, "businessType": profile.business_type, "storeCount": profile.store_count, "goal": profile.goal, "stage": profile.stage}, "checklist": checklist, "summary": {"orders": latest.basket_count, "rows": latest.source_row_count, "products": latest.product_count, "averageBasketSize": round(float(avg), 2), "rules": total_rules, "sourceFingerprint": latest.fingerprint[:12], "origin": "source"}, "rules": rules, "campaigns": campaigns, "metrics": metrics, "tasks": tasks, "evaluations": runs, "dataState": "ready"}

    def create_campaign(self, db: Session, owner_id: int, rule_id: int) -> Campaign:
        rule = db.scalar(select(AssociationRule).where(AssociationRule.id == rule_id, AssociationRule.owner_id == owner_id))
        if not rule:
            raise RetailDataError("关联规则不存在")
        campaign = Campaign(owner_id=owner_id, rule_id=rule.id, name="购物篮搭配购运营方案", status="draft", is_demo=False)
        db.add(campaign); db.flush()
        snapshot = {"ruleId": rule.id, "support": rule.support, "confidence": rule.confidence, "lift": rule.lift, "count": rule.cooccurrence_count}
        db.add(CampaignVersion(campaign_id=campaign.id, version=1, channel="淘宝闪购", copy="基于购物篮证据创建的搭配购方案，最终活动口径需运营确认。", rule_snapshot_json=json.dumps(snapshot, ensure_ascii=False)))
        db.commit(); return campaign

    def transition_task(self, db: Session, owner_id: int, task_id: int, target: str) -> OptimizationTask:
        task = db.scalar(select(OptimizationTask).where(OptimizationTask.id == task_id, OptimizationTask.owner_id == owner_id))
        if not task:
            raise RetailDataError("优化任务不存在")
        flow = {"new": "confirmed", "confirmed": "optimizing", "optimizing": "pending_verification", "pending_verification": "resolved"}
        if flow.get(task.status) != target:
            raise RetailDataError(f"不能从 {task.status} 跳转到 {target}")
        task.status = target; db.commit(); return task

    def report(self, db: Session, owner_id: int) -> str:
        data = self.overview(db, owner_id)
        if data["dataState"] != "ready":
            raise RetailDataError("暂无足够数据生成报告")
        lines = ["# 即时零售 AI 运营周报", "", "> 数据说明：购物篮商品关系来自授权源文件；时间、价格、履约、曝光与使用效果均为可复现模拟数据。", "", "## 核心数据"]
        for key, value in data["summary"].items():
            if key not in {"sourceFingerprint", "origin"}: lines.append(f"- {key}: {value}")
        lines += ["", "## 运营指标"]
        for item in data["metrics"]: lines.append(f"- {item['label']}: {item['value'] if item['value'] is not None else '数据不足'}{item['unit']}（{item['numerator']}/{item['denominator']}，模拟事件）")
        lines += ["", "## 下一步", "- 复盘高提升度关联规则，确认活动毛利与库存约束。", "- 对活动咨询失败样本进行人工标注并重新评测。", "", "本报告不声称真实销售增长；效果数据仅用于产品演示。"]
        return "\n".join(lines)
