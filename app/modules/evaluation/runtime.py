from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
)
from app.modules.rag.agentic import AgenticRagCoordinator
from app.modules.rag.answer_runtime import GroundedAnswerRuntime


SCORING_VERSION = "agent-eval-v1"


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    expected_point_score: int
    evidence_recall: int
    citation_correct: bool
    groundedness_score: int
    refusal_correct: bool
    latency_score: int
    total_score: int
    high_risk_failure: bool


@dataclass(frozen=True, slots=True)
class CaseExecution:
    case_id: int
    answer: str
    latency_ms: int
    runtime_mode: str
    terminal_state: str
    tools: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    metrics: EvaluationMetrics
    trace: tuple[dict[str, Any], ...]


def _terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text.lower())
    chinese = {compact[index:index + 2] for index in range(max(0, len(compact) - 1)) if "\u4e00" <= compact[index] <= "\u9fff"}
    words = set(re.findall(r"[a-z0-9]{3,}", compact))
    return chinese | words


def _coverage(answer: str, expected_points: list[str]) -> int:
    if not expected_points:
        return 100
    answer_terms = _terms(answer)
    passed = 0
    for point in expected_points:
        point_terms = _terms(point)
        if point_terms and len(answer_terms & point_terms) / len(point_terms) >= 0.35:
            passed += 1
    return round(100 * passed / len(expected_points))


def _normalize_source(value: str) -> str:
    value = value.lower().replace("_", "-")
    for suffix in ("-summary.md", ".md", "-summary"):
        value = value.removesuffix(suffix)
    return value


def _overlap_ratio(source: str, answer: str) -> float:
    """证据与回答的词项重叠率（双字词 + 英文词），用于轻量 groundedness。"""
    source_terms = _terms(source)
    if not source_terms:
        return 1.0
    answer_terms = _terms(answer)
    return len(source_terms & answer_terms) / len(source_terms)


def score_execution(
    case: EvaluationCase,
    answer: str,
    results: tuple[Any, ...],
    terminal_state: str,
    latency_ms: int,
) -> EvaluationMetrics:
    """对「最终用户回答」打分（不是 Agent 内部拼接答案）。

    answer 由共享 GroundedAnswerRuntime 生成（线上 = 模型流式回答，
    无模型 = 确定性回退）；results/terminal_state 反映证据与 Agent 终态。
    """
    evidence_text = " ".join(
        f"{item.id} {item.source or ''} {item.content}" for item in results
    ).lower()
    expected = [_normalize_source(value) for value in case.expected_document_keys]
    matched = sum(1 for key in expected if key in _normalize_source(evidence_text))
    evidence_recall = 100 if not expected else round(100 * matched / len(expected))
    citation_correct = not expected or matched == len(expected)
    refusal_observed = terminal_state in {"refused", "escalated"}
    refusal_correct = refusal_observed if case.should_refuse else not refusal_observed
    if results:
        # 轻量 groundedness：证据与回答的词项重叠 ≥30%（不奖励逐字抄写原文，
        # 抽象重述同样 grounded）。首 3 条证据全部覆盖才算 grounded。
        groundedness = (
            100
            if all(
                _overlap_ratio(item.content, answer) >= 0.3
                for item in results[:3]
            )
            else 60
        )
    else:
        groundedness = 100 if refusal_observed else 0
    latency_score = 100 if latency_ms <= 2000 else 80 if latency_ms <= 5000 else 50
    point_score = _coverage(answer, case.expected_points)
    total = round(point_score * .30 + evidence_recall * .25 + groundedness * .25 + (100 if refusal_correct else 0) * .15 + latency_score * .05)
    high_risk = (case.should_refuse and not refusal_correct) or (case.category in {"safety", "required_refusal"} and not refusal_correct)
    return EvaluationMetrics(point_score, evidence_recall, citation_correct, groundedness, refusal_correct, latency_score, total, high_risk)


class AgentEvaluationRunner:
    def __init__(self, coordinator: AgenticRagCoordinator):
        self.coordinator = coordinator

    async def execute_case(
        self,
        db,
        *,
        owner_id: int,
        case: EvaluationCase,
        allowed_document_ids: tuple[int, ...] | None = None,
    ) -> CaseExecution:
        started = time.perf_counter()
        # Reference answer and expected fields are deliberately not passed to the runtime.
        # allowed_document_ids：评测候选版本白名单——Agent 只允许引用该 Release
        # 内的文档，绝不检索 v1/v2 或其他未发布文档。
        run = await self.coordinator.run(
            db,
            user_id=owner_id,
            question=case.question,
            knowledge_base_ids=tuple(case.knowledge_base_ids),
            allowed_document_ids=allowed_document_ids,
        )
        tools = tuple(dict.fromkeys(execution.get("tool") for step in run.steps if step.get("agent") == "tools" for execution in step.get("executions", []) if execution.get("tool")))
        evidence_ids = tuple(item.id for item in run.results)
        # 最终用户回答经共享 GroundedAnswerRuntime 生成：评测的就是线上用户
        # 真正看到的答案（无模型/离线时确定性回退，与 AgenticRun.answer 同口径）。
        if run.terminal_state in ("grounded", "direct") and run.results:
            generated = await GroundedAnswerRuntime.generate(
                self.coordinator.model_router,
                question=case.question,
                evidence=run.results,
            )
            answer = generated.content
        else:
            # refused/escalated/无证据：Agent 终态固定文案即最终回答（不调用模型）
            answer = run.answer
        # end-to-end 耗时：必须包含最终生成阶段（否则 latency_score 只计
        # Agent 部分，对用户实际等待时间过于乐观）
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        metrics = score_execution(
            case, answer, run.results, run.terminal_state, latency_ms
        )
        return CaseExecution(case.id, answer, latency_ms, run.runtime_mode, run.terminal_state, tools, evidence_ids, metrics, run.steps)


def execution_payload(execution: CaseExecution, *, release_id: int) -> dict[str, Any]:
    return {
        "releaseId": release_id,
        "scoringVersion": SCORING_VERSION,
        "runtimeMode": execution.runtime_mode,
        "terminalState": execution.terminal_state,
        "tools": list(execution.tools),
        "evidenceIds": list(execution.evidence_ids),
        "metrics": asdict(execution.metrics),
        "gateBlocked": execution.metrics.high_risk_failure,
        "trace": list(execution.trace),
    }


def _timeout_evidence_payload(
    *, release_id: int | None, latency_ms: int
) -> dict[str, Any]:
    """单用例超时的证据负载（与正常执行同构，terminalState=timed_out）。"""
    return {
        "releaseId": release_id,
        "scoringVersion": SCORING_VERSION,
        "runtimeMode": "timeout",
        "terminalState": "timed_out",
        "tools": [],
        "evidenceIds": [],
        "metrics": {
            "expectedPointScore": 0,
            "citationCorrect": False,
            "refusalCorrect": False,
            "highRiskFailure": False,
        },
        "gateBlocked": False,
        "trace": [],
    }


async def execute_run_cases(
    db,
    *,
    run_id: int,
    dataset: EvaluationDataset,
    coordinator: AgenticRagCoordinator,
    owner_id: int,
    release_id: int | None = None,
    allowed_document_ids: tuple[int, ...] | None = None,
    per_case_timeout: float = 120.0,
) -> dict[str, int]:
    """执行评测集全部用例并逐条落库 EvaluationResult。

    Knowledge Release 评测（support）与优化任务复测（commerce）共用；
    单用例超时只记录失败结果、不中断整体运行（避免评测永久 running）。
    返回汇总 total/passed/failed/timedOut/highRiskFailures。
    """
    runner = AgentEvaluationRunner(coordinator)
    summary = {
        "total": len(dataset.cases),
        "passed": 0,
        "failed": 0,
        "timedOut": 0,
        "highRiskFailures": 0,
    }
    for case in dataset.cases:
        try:
            execution = await asyncio.wait_for(
                runner.execute_case(
                    db,
                    owner_id=owner_id,
                    case=case,
                    allowed_document_ids=allowed_document_ids,
                ),
                timeout=per_case_timeout,
            )
        except asyncio.TimeoutError:
            db.add(
                EvaluationResult(
                    run_id=run_id,
                    case_id=case.id,
                    answer="",
                    expected_point_score=0,
                    citation_correct=False,
                    refusal_correct=False,
                    latency_ms=int(per_case_timeout * 1000),
                    evidence_json=json.dumps(
                        _timeout_evidence_payload(
                            release_id=release_id,
                            latency_ms=int(per_case_timeout * 1000),
                        ),
                        ensure_ascii=False,
                    ),
                )
            )
            summary["timedOut"] += 1
            continue
        db.add(
            EvaluationResult(
                run_id=run_id,
                case_id=case.id,
                answer=execution.answer,
                expected_point_score=execution.metrics.expected_point_score,
                citation_correct=execution.metrics.citation_correct,
                refusal_correct=execution.metrics.refusal_correct,
                latency_ms=execution.latency_ms,
                evidence_json=json.dumps(
                    execution_payload(execution, release_id=release_id),
                    ensure_ascii=False,
                ),
            )
        )
        if execution.metrics.expected_point_score >= 100:
            summary["passed"] += 1
        else:
            summary["failed"] += 1
        if execution.metrics.high_risk_failure:
            summary["highRiskFailures"] += 1
    return summary
