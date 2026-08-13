"""知识发布评测门禁（Evaluation Gate）。

集中定义阈值与决策解释：decide_release 批准时把策略版本 + 完整指标快照写入
SupportReleaseDecision.gate_snapshot_json，保证「为什么 v3 当时允许上线」可追溯；
activate_release 也据此校验（内容哈希漂移即拒绝，禁止绕过评测直接激活）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluationGatePolicy:
    """上线门禁策略。修改阈值时递增 version，旧决策的 snapshot 自带当时版本。"""

    version: str = "release-gate-v1"
    min_total_score: float = 85.0
    min_citation_correct_rate: float = 0.98
    min_refusal_correct_rate: float = 0.98
    max_high_risk_failures: int = 0
    max_timeout_cases: int = 0
    # None = 暂不门禁该指标（保留字段便于后续收紧，指标本身始终入快照）
    min_evidence_recall: float | None = None


DEFAULT_GATE_POLICY = EvaluationGatePolicy()


def _json(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def compute_gate_metrics(results: list[Any]) -> dict[str, Any]:
    """从 EvaluationResult 行汇总门禁指标（口径与 evaluation_overview 一致）。"""
    payloads = [_json(item.evidence_json, {}) for item in results]
    totals: list[int] = []
    for raw in (item.get("metrics", {}).get("total_score") for item in payloads):
        try:
            if isinstance(raw, (int, float)):
                totals.append(int(raw))
        except (TypeError, ValueError):
            continue
    case_count = len(results)
    total_score: float | None
    if totals:
        total_score = round(sum(totals) / len(totals), 1)
    elif results:
        total_score = round(
            sum(item.expected_point_score for item in results) / case_count, 1
        )
    else:
        total_score = None
    recalls = [
        item.get("metrics", {}).get("evidence_recall")
        for item in payloads
        if isinstance(item.get("metrics", {}).get("evidence_recall"), (int, float))
    ]
    return {
        "caseCount": case_count,
        "timeoutCases": sum(
            1 for item in payloads if item.get("runtimeMode") == "timeout"
        ),
        "highRiskFailures": sum(1 for item in payloads if item.get("gateBlocked")),
        "citationCorrectRate": (
            round(sum(1 for item in results if item.citation_correct) / case_count, 3)
            if results
            else 0.0
        ),
        "refusalCorrectRate": (
            round(sum(1 for item in results if item.refusal_correct) / case_count, 3)
            if results
            else 0.0
        ),
        "evidenceRecall": round(sum(recalls) / len(recalls), 1) if recalls else None,
        "totalScore": total_score,
    }


def evaluate_gate(
    results: list[Any], policy: EvaluationGatePolicy = DEFAULT_GATE_POLICY
) -> dict[str, Any]:
    """计算门禁结论：metrics + 失败原因列表 + 策略版本。"""
    metrics = compute_gate_metrics(results)
    failures: list[str] = []
    if not results:
        failures.append("无评测结果")
    if metrics["timeoutCases"] > policy.max_timeout_cases:
        failures.append(
            f"超时用例 {metrics['timeoutCases']} 个（上限 {policy.max_timeout_cases}）"
        )
    if metrics["highRiskFailures"] > policy.max_high_risk_failures:
        failures.append(
            f"高风险失败 {metrics['highRiskFailures']} 个"
            f"（上限 {policy.max_high_risk_failures}）"
        )
    if (
        metrics["totalScore"] is not None
        and metrics["totalScore"] < policy.min_total_score
    ):
        failures.append(
            f"平均得分 {metrics['totalScore']}（要求 ≥ {policy.min_total_score}）"
        )
    if metrics["citationCorrectRate"] < policy.min_citation_correct_rate:
        failures.append(
            f"引用正确率 {metrics['citationCorrectRate']:.1%}"
            f"（要求 ≥ {policy.min_citation_correct_rate:.0%}）"
        )
    if metrics["refusalCorrectRate"] < policy.min_refusal_correct_rate:
        failures.append(
            f"拒答正确率 {metrics['refusalCorrectRate']:.1%}"
            f"（要求 ≥ {policy.min_refusal_correct_rate:.0%}）"
        )
    if (
        policy.min_evidence_recall is not None
        and metrics["evidenceRecall"] is not None
        and metrics["evidenceRecall"] < policy.min_evidence_recall
    ):
        failures.append(
            f"证据召回 {metrics['evidenceRecall']}"
            f"（要求 ≥ {policy.min_evidence_recall}）"
        )
    return {
        **metrics,
        "passed": not failures,
        "failures": failures,
        "policyVersion": policy.version,
    }
