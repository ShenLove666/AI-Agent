from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import date, datetime

from sqlalchemy import case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.framework.errors import AppError, ProviderUnavailableError
from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.modules.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.modules.evaluation.runtime import (
    AgentEvaluationRunner,
    SCORING_VERSION,
    execution_payload,
)
from app.modules.rag.agentic import AgenticRagCoordinator
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.orders.models import Order, OutboundMessage
from app.modules.orders.service import OrderService
from app.modules.optimization.models import OptimizationTask
from app.modules.support.outbound import OutboundService, build_customer_channel
from app.modules.support.models import (
    KnowledgeGap,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
    ReplyDecision,
    ReplySuggestion,
    SupportCase,
    SupportEscalation,
    SupportEvent,
    SupportMessage,
    SupportQualityLabel,
    SupportReleaseDecision,
)
from app.modules.users.models import User
from app.modules.provenance.models import DataSource


CASE_STATUSES = {"pending", "in_progress", "resolved", "escalated"}
CASE_PRIORITIES = {"low", "normal", "high", "urgent"}
DECISIONS = {"accepted", "edited", "rejected", "escalated"}
ESCALATION_CATEGORIES = {
    "policy_uncertain",
    "refund_exception",
    "food_safety",
    "payment_risk",
    "customer_complaint",
    "compensation_request",
    "agent_insufficient_evidence",
    "sla_timeout",
}
ESCALATION_STATUSES = {"pending", "accepted", "returned", "transferred", "resolved"}
ESCALATION_RESOLUTIONS = {
    "approved_refund",
    "approved_compensation",
    "request_more_evidence",
    "transfer_specialist",
    "return_to_agent",
}
RISK_TERMS = {
    "refund_review": ("退款", "赔付", "补偿", "优惠券"),
    "account_security": ("账号", "密码", "验证码"),
    "payment_review": ("扣款", "支付", "银行卡"),
    "food_safety": ("变质", "温度", "还能吃", "还能喝"),
}


def _json(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _without_frontmatter(content: str) -> str:
    """Remove a leading Markdown/YAML frontmatter block from display excerpts."""
    normalized = content.lstrip("\ufeff \t\r\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return content.strip()
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return content.strip()


class SupportService:
    def owner_for(self, db: Session, user: User) -> int | None:
        """商家数据归属：仅当用户是某商家组织成员时返回该组织 owner_user_id。

        不再隐式代理"最新 demo 商家"；无成员关系的用户（包括未绑定的
        平台管理员）返回 None，由调用方按读返回空 / 写拒绝处理。
        """
        from app.modules.users.access import resolve_owner

        return resolve_owner(db, user)

    def list_cases(
        self,
        db: Session,
        owner_id: int,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee_id: int | None = None,
        label: str | None = None,
        unread: bool | None = None,
        search: str | None = None,
    ) -> list[dict]:
        query = select(SupportCase).where(SupportCase.owner_id == owner_id)
        if status:
            query = query.where(SupportCase.status == status)
        if priority:
            query = query.where(SupportCase.priority == priority)
        if assignee_id is not None:
            query = query.where(SupportCase.assignee_id == assignee_id)
        if label:
            query = query.where(SupportCase.labels_json.contains(f'"{label}"'))
        if unread is not None:
            query = query.where(SupportCase.unread.is_(unread))
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    SupportCase.subject.ilike(term),
                    SupportCase.customer_name.ilike(term),
                    SupportCase.case_key.ilike(term),
                )
            )
        cases = list(
            db.scalars(
                query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc())
            )
        )
        return [self._case_summary(db, item) for item in cases]

    def detail(self, db: Session, owner_id: int, case_id: int) -> dict:
        case = self.require_case(db, owner_id, case_id)
        source = (
            db.get(DataSource, case.source_data_id) if case.source_data_id else None
        )
        messages = list(
            db.scalars(
                select(SupportMessage)
                .where(SupportMessage.case_id == case.id)
                .order_by(SupportMessage.created_at, SupportMessage.id)
            )
        )
        events = list(
            db.scalars(
                select(SupportEvent)
                .where(SupportEvent.case_id == case.id)
                .order_by(SupportEvent.occurred_at, SupportEvent.id)
            )
        )
        suggestions = list(
            db.scalars(
                select(ReplySuggestion)
                .where(ReplySuggestion.case_id == case.id)
                .order_by(ReplySuggestion.id.desc())
            )
        )
        decisions = {
            item.suggestion_id: item
            for item in db.scalars(
                select(ReplyDecision).where(ReplyDecision.case_id == case.id)
            )
        }
        return {
            **self._case_summary(db, case),
            "resolutionCode": case.resolution_code,
            "resolutionNote": case.resolution_note,
            "provenance": {
                "sourceRecordKey": case.source_record_key,
                "generatorVersion": case.generator_version,
                "generatorSeed": case.generator_seed,
                "fieldLineage": _json(case.field_lineage_json, {}),
                "dataSource": (
                    {
                        "id": source.id,
                        "datasetKey": source.dataset_key,
                        "version": source.version,
                        "title": source.title,
                        "publisher": source.publisher,
                        "sourceUri": source.source_uri,
                        "license": source.license,
                        "limitations": _json(source.limitations_json, []),
                    }
                    if source
                    else None
                ),
            },
            "messages": [
                {
                    "id": item.id,
                    "role": item.role,
                    "content": item.content,
                    "sentToCustomer": item.sent_to_customer,
                    "suggestionId": item.suggestion_id,
                    "createdAt": item.created_at.isoformat(),
                }
                for item in messages
            ],
            "events": [
                {
                    "id": item.id,
                    "type": item.event_type,
                    "payload": _json(item.payload_json, {}),
                    "occurredAt": item.occurred_at.isoformat(),
                }
                for item in events
            ],
            "suggestions": [
                self._suggestion(item, decisions.get(item.id)) for item in suggestions
            ],
        }

    def case_provenance(self, db: Session, owner_id: int, case_id: int) -> dict:
        return self.detail(db, owner_id, case_id)["provenance"]

    def workspace(self, db: Session, owner_id: int, case_id: int) -> dict:
        case = self.require_case(db, owner_id, case_id)
        suggestion = db.scalar(
            select(ReplySuggestion)
            .where(ReplySuggestion.case_id == case.id)
            .order_by(ReplySuggestion.id.desc())
            .limit(1)
        )
        decision = (
            db.scalar(
                select(ReplyDecision).where(
                    ReplyDecision.suggestion_id == suggestion.id
                )
            )
            if suggestion
            else None
        )
        outbound = list(
            db.scalars(
                select(OutboundMessage)
                .where(
                    OutboundMessage.owner_id == owner_id,
                    OutboundMessage.case_id == case.id,
                )
                .order_by(OutboundMessage.id.desc())
            )
        )
        order = (
            db.scalar(
                select(Order).where(
                    Order.id == case.order_id,
                    Order.owner_id == owner_id,
                )
            )
            if case.order_id is not None
            else None
        )
        message_count = int(
            db.scalar(
                select(func.count(SupportMessage.id)).where(
                    SupportMessage.case_id == case.id
                )
            )
            or 0
        )
        suggestion_count = int(
            db.scalar(
                select(func.count(ReplySuggestion.id)).where(
                    ReplySuggestion.case_id == case.id
                )
            )
            or 0
        )
        return {
            "case": self._case_summary(db, case),
            "order": (
                OrderService().detail(db, owner_id, order.order_no) if order else None
            ),
            "activeSuggestion": (
                self._suggestion(suggestion, decision) if suggestion else None
            ),
            "outboundMessages": [self._outbound(item) for item in outbound],
            "diagnostics": {
                "messageCount": message_count,
                "suggestionCount": suggestion_count,
                "outboundCount": len(outbound),
            },
        }

    def coverage(self, db: Session, owner_id: int) -> dict:
        cases = list(
            db.scalars(select(SupportCase).where(SupportCase.owner_id == owner_id))
        )
        categories: dict[str, int] = {}
        statuses: dict[str, int] = {}
        source_versions: dict[str, int] = {}
        demo = 0
        for case in cases:
            labels = _json(case.labels_json, [])
            known_categories = {
                "refund",
                "cancellation",
                "promotion",
                "product",
                "delivery",
                "payment",
                "food_safety",
                "invoice",
                "account",
            }
            category = next(
                (
                    str(item).removeprefix("category:")
                    for item in labels
                    if str(item).removeprefix("category:") in known_categories
                ),
                "uncategorized",
            )
            categories[category] = categories.get(category, 0) + 1
            statuses[case.status] = statuses.get(case.status, 0) + 1
            version = case.generator_version or "ordinary"
            source_versions[version] = source_versions.get(version, 0) + 1
            demo += int(case.is_demo)
        total = len(cases)
        return {
            "totalCases": total,
            "categories": categories,
            "statuses": statuses,
            "sourceVersions": source_versions,
            "demoCases": demo,
            "ordinaryCases": total - demo,
            "provenance": "demo"
            if total and demo == total
            else ("mixed" if demo else "production"),
            "unsupportedSegments": [
                key
                for key in (
                    "refund",
                    "cancellation",
                    "promotion",
                    "product",
                    "delivery",
                    "payment",
                    "food_safety",
                    "invoice",
                    "account",
                )
                if categories.get(key, 0) == 0
            ],
        }

    def require_case(self, db: Session, owner_id: int, case_id: int) -> SupportCase:
        item = db.scalar(
            select(SupportCase).where(
                SupportCase.id == case_id, SupportCase.owner_id == owner_id
            )
        )
        if item is None:
            raise AppError("SUPPORT_CASE_NOT_FOUND", "客服工单不存在", 404)
        return item

    def transition(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        *,
        status: str,
        expected_version: int,
        resolution_code: str | None = None,
        resolution_note: str | None = None,
        reason: str | None = None,
    ) -> dict:
        if status not in CASE_STATUSES:
            raise AppError("INVALID_CASE_STATUS", "不支持的工单状态", 422)
        case = self.require_case(db, owner_id, case_id)
        if case.version != expected_version:
            raise AppError(
                "CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409
            )
        if status == "resolved" and not resolution_code:
            raise AppError(
                "RESOLUTION_CODE_REQUIRED", "解决工单前必须选择解决结果", 422
            )
        previous = case.status
        case.status = status
        case.resolution_code = resolution_code if status == "resolved" else None
        case.resolution_note = (
            resolution_note if status == "resolved" else case.resolution_note
        )
        case.unread = False
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(
            db,
            case,
            actor_id,
            "status_changed",
            {"from": previous, "to": status, "reason": reason},
        )
        db.commit()
        return self.detail(db, owner_id, case.id)

    def assign(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        assignee_id: int | None,
        expected_version: int,
    ) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if case.version != expected_version:
            raise AppError(
                "CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409
            )
        if assignee_id is not None and db.get(User, assignee_id) is None:
            raise AppError("ASSIGNEE_NOT_FOUND", "负责人不存在", 422)
        case.assignee_id = assignee_id
        if case.status == "pending" and assignee_id is not None:
            case.status = "in_progress"
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, "case_assigned", {"assigneeId": assignee_id})
        db.commit()
        return self.detail(db, owner_id, case.id)

    def set_labels(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        labels: list[str],
        expected_version: int,
    ) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if case.version != expected_version:
            raise AppError(
                "CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409
            )
        clean = sorted({item.strip() for item in labels if item.strip()})[:12]
        case.labels_json = json.dumps(clean, ensure_ascii=False)
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, "labels_changed", {"labels": clean})
        db.commit()
        return self.detail(db, owner_id, case.id)

    def manual_reply(
        self, db: Session, owner_id: int, case_id: int, actor_id: int, content: str
    ) -> dict:
        case = self.require_case(db, owner_id, case_id)
        clean_content = content.strip()
        if not clean_content:
            raise AppError("EMPTY_REPLY", "回复内容不能为空", 422)
        OutboundService(build_customer_channel()).confirm(
            db,
            owner_id=owner_id,
            case_id=case.id,
            actor_id=actor_id,
            content=clean_content,
            expected_version=case.version,
            idempotency_key=f"legacy-manual:{case.id}:{case.version}",
        )
        return self.detail(db, owner_id, case.id)

    async def generate_suggestion(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        model_router,
        coordinator: AgenticRagCoordinator | None = None,
    ) -> dict:
        case = self.require_case(db, owner_id, case_id)
        release = db.scalar(
            select(KnowledgeRelease).where(
                KnowledgeRelease.owner_id == owner_id,
                KnowledgeRelease.status == "published",
                KnowledgeRelease.is_active.is_(True),
            )
        )
        latest_customer = db.scalar(
            select(SupportMessage)
            .where(SupportMessage.case_id == case.id, SupportMessage.role == "customer")
            .order_by(SupportMessage.id.desc())
            .limit(1)
        )
        question = latest_customer.content if latest_customer else case.subject
        # 关联订单：把订单号注入问题，让统一 Agent Runtime 自主拉取订单/履约/退款/顾客事实
        order_no: str | None = None
        if case.order_id is not None:
            order = db.get(Order, case.order_id)
            if order is not None and order.owner_id == owner_id:
                order_no = order.order_no
        agent_question = question
        if order_no and order_no not in agent_question:
            agent_question = f"{question}\n（关联订单号：{order_no}）"
        # 当前商家已启用的知识库，供 Agent 检索政策证据
        knowledge_base_ids = tuple(
            db.scalars(
                select(KnowledgeBase.id).where(KnowledgeBase.owner_id == owner_id)
            )
        )
        risk_flags = [
            flag
            for flag, terms in RISK_TERMS.items()
            if any(term in question for term in terms)
        ]
        started = time.perf_counter()
        status = "completed"
        content: str | None = None
        error_code: str | None = None
        model_id = "unconfigured"
        resolution: dict | None = None
        citations: list[dict] = []
        run = None
        if coordinator is None or (
            coordinator.model_router is None and release is None
        ):
            status = "provider_unavailable"
            error_code = "MODEL_PROVIDER_UNAVAILABLE"
        else:
            try:
                run = await coordinator.run(
                    db,
                    user_id=owner_id,
                    question=agent_question,
                    knowledge_base_ids=knowledge_base_ids,
                )
                results = list(run.results)
                citations = [
                    self._evidence_citation(item, index)
                    for index, item in enumerate(results, 1)
                    if item.metadata.get("factType") in (None, "policy")
                    or item.channel.startswith("knowledge")
                ]
                model_id = run.runtime_mode
                if (
                    run.terminal_state == "grounded"
                    and run.review_details.decision == "ready"
                ):
                    status = "completed"
                    content = self._compose_draft(run, question, order_no)
                    resolution = self._build_resolution(
                        run, question, order_no, risk_flags
                    )
                else:
                    status = "insufficient_evidence"
                    error_code = (
                        "ESCALATED"
                        if run.terminal_state == "escalated"
                        else "INSUFFICIENT_EVIDENCE"
                    )
                    resolution = self._build_resolution(
                        run, question, order_no, risk_flags
                    )
            except ProviderUnavailableError:
                status = "provider_unavailable"
                error_code = "MODEL_PROVIDER_UNAVAILABLE"
            except Exception:
                db.rollback()
                status = "failed"
                error_code = "SUGGESTION_FAILED"
        suggestion = ReplySuggestion(
            case_id=case.id,
            requested_by=actor_id,
            knowledge_release_id=release.id if release else None,
            status=status,
            content=content,
            citations_json=json.dumps(citations, ensure_ascii=False),
            risk_flags_json=json.dumps(risk_flags, ensure_ascii=False),
            model_id=model_id,
            prompt_version="support-v2-agentic",
            config_snapshot_json=json.dumps(
                {
                    "knowledgeVersion": release.version if release else None,
                    "runtimeMode": run.runtime_mode if run else None,
                    "terminalState": run.terminal_state if run else None,
                    "resolution": resolution,
                },
                ensure_ascii=False,
            ),
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_code=error_code,
        )
        db.add(suggestion)
        db.flush()
        self._event(
            db,
            case,
            actor_id,
            "suggestion_generated",
            {"suggestionId": suggestion.id, "status": status},
        )
        db.commit()
        return self._suggestion(suggestion, None)

    def decide(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        suggestion_id: int,
        actor_id: int,
        decision: str,
        final_content: str | None,
        reason: str | None,
    ) -> dict:
        if decision not in DECISIONS:
            raise AppError("INVALID_REPLY_DECISION", "不支持的审核动作", 422)
        case = self.require_case(db, owner_id, case_id)
        suggestion = db.scalar(
            select(ReplySuggestion).where(
                ReplySuggestion.id == suggestion_id, ReplySuggestion.case_id == case.id
            )
        )
        if suggestion is None:
            raise AppError("SUGGESTION_NOT_FOUND", "回复建议不存在", 404)
        if (
            db.scalar(
                select(ReplyDecision.id).where(
                    ReplyDecision.suggestion_id == suggestion.id
                )
            )
            is not None
        ):
            raise AppError("SUGGESTION_ALREADY_REVIEWED", "该建议已经完成审核", 409)
        if decision in {"accepted", "edited"}:
            outgoing = (
                final_content if decision == "edited" else suggestion.content
            ) or ""
            if not outgoing.strip():
                raise AppError("FINAL_REPLY_REQUIRED", "发送前必须填写最终回复", 422)
        else:
            outgoing = None
        item = ReplyDecision(
            suggestion_id=suggestion.id,
            case_id=case.id,
            actor_id=actor_id,
            decision=decision,
            final_content=outgoing,
            reason=reason,
        )
        db.add(item)
        if outgoing:
            self._event(
                db,
                case,
                actor_id,
                f"suggestion_{decision}",
                {"suggestionId": suggestion.id, "reason": reason},
            )
            OutboundService(build_customer_channel()).confirm(
                db,
                owner_id=owner_id,
                case_id=case.id,
                actor_id=actor_id,
                content=outgoing,
                expected_version=case.version,
                idempotency_key=f"legacy-decision:{suggestion.id}",
                suggestion_id=suggestion.id,
            )
            return self.detail(db, owner_id, case.id)
        if decision == "escalated":
            case.status = "escalated"
        case.unread = False
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(
            db,
            case,
            actor_id,
            f"suggestion_{decision}",
            {"suggestionId": suggestion.id, "reason": reason},
        )
        db.commit()
        return self.detail(db, owner_id, case.id)

    def metrics(self, db: Session, owner_id: int) -> dict:
        total = int(
            db.scalar(
                select(func.count(SupportCase.id)).where(
                    SupportCase.owner_id == owner_id
                )
            )
            or 0
        )
        statuses = dict(
            db.execute(
                select(SupportCase.status, func.count())
                .where(SupportCase.owner_id == owner_id)
                .group_by(SupportCase.status)
            ).all()
        )
        decisions = dict(
            db.execute(
                select(ReplyDecision.decision, func.count())
                .join(SupportCase, SupportCase.id == ReplyDecision.case_id)
                .where(SupportCase.owner_id == owner_id)
                .group_by(ReplyDecision.decision)
            ).all()
        )
        reviewed = sum(int(value) for value in decisions.values())
        suggestions = int(
            db.scalar(
                select(func.count(ReplySuggestion.id))
                .join(SupportCase)
                .where(SupportCase.owner_id == owner_id)
            )
            or 0
        )
        cited = int(
            db.scalar(
                select(func.count(ReplySuggestion.id))
                .join(SupportCase)
                .where(
                    SupportCase.owner_id == owner_id,
                    ReplySuggestion.citations_json != "[]",
                )
            )
            or 0
        )
        demo = int(
            db.scalar(
                select(func.count(SupportCase.id)).where(
                    SupportCase.owner_id == owner_id, SupportCase.is_demo.is_(True)
                )
            )
            or 0
        )
        return {
            "totalCases": total,
            "pendingCases": int(statuses.get("pending", 0)),
            "resolvedCases": int(statuses.get("resolved", 0)),
            "escalatedCases": int(statuses.get("escalated", 0)),
            "resolutionRate": round(int(statuses.get("resolved", 0)) / total * 100, 1)
            if total
            else None,
            "acceptanceRate": round(
                (int(decisions.get("accepted", 0)) + int(decisions.get("edited", 0)))
                / reviewed
                * 100,
                1,
            )
            if reviewed
            else None,
            "editRate": round(int(decisions.get("edited", 0)) / reviewed * 100, 1)
            if reviewed
            else None,
            "citationCoverage": round(cited / suggestions * 100, 1)
            if suggestions
            else None,
            "provenance": "demo"
            if total and demo == total
            else ("mixed" if demo else "production"),
        }

    def list_releases(self, db: Session, owner_id: int) -> list[dict]:
        releases = list(
            db.scalars(
                select(KnowledgeRelease)
                .where(KnowledgeRelease.owner_id == owner_id)
                .order_by(KnowledgeRelease.id.desc())
            )
        )
        return [self._release(db, item) for item in releases]

    def knowledge_sources(self, db: Session, owner_id: int) -> list[dict]:
        documents = list(
            db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.uploader_id == owner_id)
                .order_by(KnowledgeDocument.id)
            )
        )
        return [
            {
                "id": item.id,
                "title": item.source_title or item.filename,
                "filename": item.filename,
                "contentOrigin": item.content_origin,
                "publisher": item.source_publisher,
                "canonicalUrl": item.source_url,
                "retrievedAt": item.source_retrieved_at.isoformat()
                if item.source_retrieved_at
                else None,
                "jurisdiction": item.source_jurisdiction,
                "nextReviewAt": item.next_review_at.isoformat()
                if item.next_review_at
                else None,
                "reviewStatus": item.review_status,
                "applicability": _json(item.applicability_json, []),
                "exclusions": _json(item.exclusions_json, []),
                "usageNote": item.license_or_usage_note or item.source_usage_note,
                "status": item.status,
                "enabled": item.enabled,
                "checksum": item.demo_content_sha256,
            }
            for item in documents
        ]

    def create_release(
        self,
        db: Session,
        owner_id: int,
        actor_id: int,
        version: str,
        title: str,
        document_ids: list[int],
    ) -> dict:
        version, title = version.strip(), title.strip()
        if not version or not title or not document_ids:
            raise AppError(
                "INVALID_KNOWLEDGE_RELEASE", "版本、标题和知识文档不能为空", 422
            )
        if db.scalar(
            select(KnowledgeRelease.id).where(
                KnowledgeRelease.owner_id == owner_id,
                KnowledgeRelease.version == version,
            )
        ):
            raise AppError("KNOWLEDGE_RELEASE_EXISTS", "该知识版本已存在", 409)
        documents = list(
            db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id.in_(set(document_ids)),
                    KnowledgeDocument.uploader_id == owner_id,
                )
            )
        )
        if len(documents) != len(set(document_ids)):
            raise AppError(
                "KNOWLEDGE_DOCUMENT_NOT_FOUND",
                "部分知识文档不存在或不属于当前商家",
                404,
            )
        snapshots = [
            (
                item,
                item.demo_content_sha256
                or hashlib.sha256(
                    f"{item.id}:{item.filename}:{item.file_size}".encode()
                ).hexdigest(),
            )
            for item in documents
        ]
        content_hash = hashlib.sha256(
            "|".join(sorted(item_hash for _, item_hash in snapshots)).encode()
        ).hexdigest()
        release = KnowledgeRelease(
            owner_id=owner_id,
            version=version,
            title=title,
            status="draft",
            processing_status="ready",
            content_hash=content_hash,
            retrieval_mode="keyword",
        )
        db.add(release)
        db.flush()
        for document, document_hash in snapshots:
            db.add(
                KnowledgeReleaseDocument(
                    release_id=release.id,
                    document_id=document.id,
                    document_hash=document_hash,
                    filename_snapshot=document.filename,
                )
            )
        db.commit()
        return self._release(db, release)

    def publish_release(
        self, db: Session, owner_id: int, release_id: int, actor_id: int
    ) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status == "published":
            return self._release(db, release)
        memberships = list(
            db.scalars(
                select(KnowledgeReleaseDocument).where(
                    KnowledgeReleaseDocument.release_id == release.id
                )
            )
        )
        if not memberships:
            raise AppError("EMPTY_KNOWLEDGE_RELEASE", "知识版本没有可发布文档", 422)
        document_ids = [item.document_id for item in memberships]
        documents = list(
            db.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
            )
        )
        stale = [
            item.filename
            for item in documents
            if item.review_status != "current"
            or (item.next_review_at is not None and item.next_review_at < date.today())
        ]
        unattributed = [
            item.filename
            for item in documents
            if item.content_origin == "public_summary"
            and (
                not item.source_title
                or not item.source_url
                or not item.source_publisher
                or not item.source_retrieved_at
                or not _json(item.applicability_json, [])
                or not (item.license_or_usage_note or item.source_usage_note)
            )
        ]
        conflicts = [
            item.filename
            for item in documents
            if (
                item.content_origin == "public_summary"
                and item.source_jurisdiction == "虚构演示商家"
            )
            or (
                item.content_origin == "synthetic"
                and bool(item.source_url or item.source_publisher)
            )
            or (
                item.content_origin in {"public_summary", "synthetic"}
                and not _json(item.applicability_json, [])
            )
        ]
        hash_drift = []
        for membership in memberships:
            document = db.get(KnowledgeDocument, membership.document_id)
            current_hash = (
                document.demo_content_sha256
                or hashlib.sha256(
                    f"{document.id}:{document.filename}:{document.file_size}".encode()
                ).hexdigest()
            )
            if current_hash != membership.document_hash:
                hash_drift.append(membership.filename_snapshot)
        if stale or unattributed or conflicts or hash_drift:
            release.processing_status = "blocked"
            db.commit()
            raise AppError(
                "KNOWLEDGE_PROVENANCE_INVALID",
                "知识版本存在过期、缺少来源、来源冲突或内容漂移的文档",
                409,
                {
                    "stale": stale,
                    "unattributed": unattributed,
                    "conflicts": conflicts,
                    "hashDrift": hash_drift,
                },
            )
        ready = int(
            db.scalar(
                select(func.count(KnowledgeDocument.id)).where(
                    KnowledgeDocument.id.in_(document_ids),
                    KnowledgeDocument.status.in_(("ready", "indexed")),
                    KnowledgeDocument.enabled.is_(True),
                )
            )
            or 0
        )
        chunk_count = int(
            db.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.document_id.in_(document_ids),
                    KnowledgeChunk.enabled.is_(True),
                )
            )
            or 0
        )
        if ready != len(document_ids) or chunk_count == 0:
            release.processing_status = "blocked"
            db.commit()
            raise AppError(
                "KNOWLEDGE_RELEASE_NOT_READY", "存在未完成解析或无可检索分块的文档", 409
            )
        release.status = "published"
        release.processing_status = "ready"
        release.published_by = actor_id
        release.published_at = datetime.utcnow()
        db.commit()
        return self._release(db, release)

    def activate_release(self, db: Session, owner_id: int, release_id: int) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError(
                "KNOWLEDGE_RELEASE_NOT_PUBLISHED", "只能启用已发布知识版本", 409
            )
        for item in db.scalars(
            select(KnowledgeRelease).where(
                KnowledgeRelease.owner_id == owner_id,
                KnowledgeRelease.is_active.is_(True),
            )
        ):
            item.is_active = False
        release.is_active = True
        db.commit()
        return self._release(db, release)

    def list_gaps(self, db: Session, owner_id: int) -> list[dict]:
        items = list(
            db.scalars(
                select(KnowledgeGap)
                .where(KnowledgeGap.owner_id == owner_id)
                .order_by(
                    KnowledgeGap.status,
                    KnowledgeGap.occurrence_count.desc(),
                    KnowledgeGap.id.desc(),
                )
            )
        )
        return [
            {
                "id": item.id,
                "title": item.title,
                "category": item.category,
                "severity": item.severity,
                "status": item.status,
                "occurrenceCount": item.occurrence_count,
                "ownerUserId": item.owner_user_id,
                "resolvingReleaseId": item.resolving_release_id,
                "evidence": _json(item.evidence_json, []),
                "isDemo": item.is_demo,
            }
            for item in items
        ]

    def add_quality_label(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        verdict: str,
        failure_category: str | None,
        severity: str | None,
        note: str | None,
        suggestion_id: int | None = None,
    ) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if verdict not in {"passed", "failed"}:
            raise AppError("INVALID_QUALITY_VERDICT", "质检结论必须为通过或失败", 422)
        if verdict == "failed" and not failure_category:
            raise AppError("FAILURE_CATEGORY_REQUIRED", "质检失败必须选择失败类型", 422)
        label = SupportQualityLabel(
            owner_id=owner_id,
            case_id=case.id,
            suggestion_id=suggestion_id,
            reviewer_id=actor_id,
            verdict=verdict,
            failure_category=failure_category,
            severity=severity,
            note=note,
        )
        db.add(label)
        if verdict == "failed":
            fingerprint = hashlib.sha256(
                f"{owner_id}:{failure_category}:{case.subject.strip().lower()}".encode()
            ).hexdigest()
            gap = db.scalar(
                select(KnowledgeGap).where(
                    KnowledgeGap.owner_id == owner_id,
                    KnowledgeGap.fingerprint == fingerprint,
                )
            )
            evidence = {
                "caseId": case.id,
                "suggestionId": suggestion_id,
                "labelId": None,
            }
            if gap is None:
                gap = KnowledgeGap(
                    owner_id=owner_id,
                    fingerprint=fingerprint,
                    title=f"{case.subject}：{failure_category}",
                    category=failure_category or "other",
                    severity=severity or "medium",
                    evidence_json="[]",
                    is_demo=case.is_demo,
                )
                db.add(gap)
            else:
                gap.occurrence_count += 1
            db.flush()
            evidence["labelId"] = label.id
            entries = _json(gap.evidence_json, [])
            entries.append(evidence)
            gap.evidence_json = json.dumps(entries[-20:], ensure_ascii=False)
            gap.updated_at = datetime.utcnow()
            self._create_task_from_gap(db, owner_id, gap)
        db.commit()
        return {
            "id": label.id,
            "caseId": case.id,
            "verdict": label.verdict,
            "failureCategory": label.failure_category,
            "severity": label.severity,
            "note": label.note,
        }

    def _create_task_from_gap(
        self, db: Session, owner_id: int, gap: KnowledgeGap
    ) -> None:
        """客服质检失败（知识缺口）→ 自动创建优化任务（幂等去重）。"""
        existing = db.scalar(
            select(OptimizationTask).where(
                OptimizationTask.owner_id == owner_id,
                OptimizationTask.source_type == "knowledge_gap",
                OptimizationTask.source_id == str(gap.id),
            )
        )
        if existing:
            return
        case_id = None
        for entry in _json(gap.evidence_json, []):
            if isinstance(entry, dict) and entry.get("caseId"):
                case_id = int(entry["caseId"])
                break
        db.add(
            OptimizationTask(
                owner_id=owner_id,
                source_type="knowledge_gap",
                source_id=str(gap.id),
                title=f"补齐知识缺口：{gap.title}",
                status="new",
                target_metric="知识命中率",
                before_evidence_json=json.dumps(
                    {
                        "origin": "quality_label",
                        "gapId": gap.id,
                        "category": gap.category,
                    },
                    ensure_ascii=False,
                ),
                support_case_id=case_id,
                is_demo=gap.is_demo,
            )
        )

    def resolve_gap(
        self, db: Session, owner_id: int, gap_id: int, actor_id: int, release_id: int
    ) -> dict:
        gap = db.scalar(
            select(KnowledgeGap).where(
                KnowledgeGap.id == gap_id, KnowledgeGap.owner_id == owner_id
            )
        )
        if gap is None:
            raise AppError("KNOWLEDGE_GAP_NOT_FOUND", "知识缺口不存在", 404)
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError(
                "KNOWLEDGE_RELEASE_NOT_PUBLISHED", "解决缺口必须绑定已发布版本", 409
            )
        gap.status, gap.owner_user_id, gap.resolving_release_id = (
            "resolved",
            actor_id,
            release.id,
        )
        gap.updated_at = datetime.utcnow()
        db.commit()
        return next(
            item for item in self.list_gaps(db, owner_id) if item["id"] == gap.id
        )

    def quality_overview(self, db: Session, owner_id: int) -> dict:
        labels = list(
            db.scalars(
                select(SupportQualityLabel).where(
                    SupportQualityLabel.owner_id == owner_id
                )
            )
        )
        categories: dict[str, int] = {}
        for item in labels:
            key = item.failure_category or "passed"
            categories[key] = categories.get(key, 0) + 1
        gaps = self.list_gaps(db, owner_id)
        return {
            "reviewed": len(labels),
            "passed": sum(1 for item in labels if item.verdict == "passed"),
            "failureCategories": categories,
            "openGaps": sum(1 for item in gaps if item["status"] == "open"),
            "gaps": gaps,
            "provenance": self.metrics(db, owner_id)["provenance"],
        }

    # ------------------------------------------------------------------
    # 客服升级（主管队列）
    # ------------------------------------------------------------------

    def _escalation_vo(
        self, db: Session, item: SupportEscalation, case: SupportCase | None = None
    ) -> dict:
        return {
            "id": item.id,
            "caseId": item.case_id,
            "raisedBy": item.raised_by,
            "assignedTo": item.assigned_to,
            "category": item.category,
            "reason": item.reason,
            "riskLevel": item.risk_level,
            "status": item.status,
            "resolution": item.resolution,
            "resolutionNote": item.resolution_note,
            "aiDiagnosis": _json(item.ai_diagnosis_json, {}),
            "createdAt": item.created_at.isoformat(),
            "raisedAt": item.raised_at.isoformat(),
            "acceptedAt": item.accepted_at.isoformat() if item.accepted_at else None,
            "resolvedAt": item.resolved_at.isoformat() if item.resolved_at else None,
            "isDemo": item.is_demo,
            "case": (
                SupportService._case_summary(db, case) if case is not None else None
            ),
        }

    def raise_escalation(
        self,
        db: Session,
        owner_id: int,
        case_id: int,
        actor_id: int,
        category: str,
        reason: str,
        risk_level: str = "medium",
        ai_diagnosis: dict | None = None,
    ) -> dict:
        if category not in ESCALATION_CATEGORIES:
            raise AppError("INVALID_ESCALATION_CATEGORY", "不支持的升级分类", 422)
        if risk_level not in {"low", "medium", "high"}:
            raise AppError("INVALID_ESCALATION_RISK", "不支持的风险等级", 422)
        if not reason.strip():
            raise AppError("ESCALATION_REASON_REQUIRED", "升级必须说明原因", 422)
        case = self.require_case(db, owner_id, case_id)
        # 同一工单存在未完结升级时不允许重复升级
        active = db.scalar(
            select(SupportEscalation.id).where(
                SupportEscalation.case_id == case.id,
                SupportEscalation.status.in_(("pending", "accepted")),
            )
        )
        if active is not None:
            raise AppError("ESCALATION_ALREADY_ACTIVE", "该工单已有待处理的升级", 409)
        item = SupportEscalation(
            owner_id=owner_id,
            case_id=case.id,
            raised_by=actor_id,
            category=category,
            reason=reason.strip(),
            risk_level=risk_level,
            status="pending",
            ai_diagnosis_json=json.dumps(ai_diagnosis or {}, ensure_ascii=False),
            is_demo=case.is_demo,
        )
        db.add(item)
        db.flush()
        case.status = "escalated"
        case.updated_at = datetime.utcnow()
        self._event(
            db,
            case,
            actor_id,
            "case_escalated",
            {
                "escalationId": item.id,
                "category": category,
                "riskLevel": risk_level,
                "reason": reason.strip(),
            },
        )
        db.commit()
        return self._escalation_vo(db, item, case)

    def escalation_queue(self, db: Session, owner_id: int) -> list[dict]:
        """主管队列：待处理与已接收的升级，按风险/时间排序。"""
        rows = db.execute(
            select(SupportEscalation, SupportCase)
            .join(SupportCase, SupportCase.id == SupportEscalation.case_id)
            .where(SupportEscalation.owner_id == owner_id)
            .order_by(
                sql_case(
                    (SupportEscalation.risk_level == "high", 0),
                    (SupportEscalation.risk_level == "medium", 1),
                    else_=2,
                ),
                SupportEscalation.raised_at.asc(),
            )
        ).all()
        return [self._escalation_vo(db, item, case) for item, case in rows]

    def accept_escalation(
        self, db: Session, owner_id: int, escalation_id: int, actor_id: int
    ) -> dict:
        item, case = self._require_escalation(db, owner_id, escalation_id)
        if item.status not in {"pending"}:
            raise AppError("ESCALATION_NOT_PENDING", "升级已被处理或退回", 409)
        item.status = "accepted"
        item.assigned_to = actor_id
        item.accepted_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        case.assignee_id = actor_id
        case.updated_at = datetime.utcnow()
        self._event(
            db, case, actor_id, "escalation_accepted", {"escalationId": item.id}
        )
        db.commit()
        return self._escalation_vo(db, item, case)

    def resolve_escalation(
        self,
        db: Session,
        owner_id: int,
        escalation_id: int,
        actor_id: int,
        resolution: str,
        resolution_note: str | None = None,
    ) -> dict:
        if resolution not in ESCALATION_RESOLUTIONS:
            raise AppError("INVALID_ESCALATION_RESOLUTION", "不支持的处理决议", 422)
        item, case = self._require_escalation(db, owner_id, escalation_id)
        if item.status not in {"pending", "accepted"}:
            raise AppError("ESCALATION_NOT_ACTIVE", "升级不在处理中", 409)
        item.resolution = resolution
        item.resolution_note = resolution_note
        now = datetime.utcnow()
        if resolution == "request_more_evidence":
            item.status = "accepted"
            item.assigned_to = item.assigned_to or actor_id
            item.accepted_at = item.accepted_at or now
            item.resolved_at = None
            case.status = "escalated"
            event_type = "escalation_evidence_requested"
        elif resolution == "transfer_specialist":
            item.status = "transferred"
            item.assigned_to = item.assigned_to or actor_id
            item.accepted_at = item.accepted_at or now
            item.resolved_at = now
            case.status = "escalated"
            event_type = "escalation_transferred"
        elif resolution == "return_to_agent":
            item.status = "returned"
            item.resolved_at = now
            case.status = "in_progress"
            event_type = "escalation_returned"
        else:
            item.status = "resolved"
            item.resolved_at = now
            case.status = "resolved"
            event_type = "escalation_resolved"
        item.updated_at = now
        case.updated_at = now
        self._event(
            db,
            case,
            actor_id,
            event_type,
            {
                "escalationId": item.id,
                "resolution": resolution,
                "note": resolution_note,
            },
        )
        db.commit()
        return self._escalation_vo(db, item, case)

    def return_escalation(
        self,
        db: Session,
        owner_id: int,
        escalation_id: int,
        actor_id: int,
        note: str | None = None,
    ) -> dict:
        """主管退回：工单回到普通客服继续处理，升级标记为 returned。"""
        item, case = self._require_escalation(db, owner_id, escalation_id)
        if item.status not in {"pending", "accepted"}:
            raise AppError("ESCALATION_NOT_ACTIVE", "升级不在处理中", 409)
        item.status = "returned"
        item.resolution = "return_to_agent"
        item.resolution_note = note or "主管退回客服继续处理"
        item.resolved_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        case.status = "in_progress"
        case.updated_at = datetime.utcnow()
        self._event(
            db,
            case,
            actor_id,
            "escalation_returned",
            {"escalationId": item.id, "note": note},
        )
        db.commit()
        return self._escalation_vo(db, item, case)

    def _require_escalation(
        self, db: Session, owner_id: int, escalation_id: int
    ) -> tuple[SupportEscalation, SupportCase]:
        row = db.execute(
            select(SupportEscalation, SupportCase)
            .join(SupportCase, SupportCase.id == SupportEscalation.case_id)
            .where(
                SupportEscalation.id == escalation_id,
                SupportEscalation.owner_id == owner_id,
            )
        ).first()
        if row is None:
            raise AppError("ESCALATION_NOT_FOUND", "升级记录不存在", 404)
        return row[0], row[1]

    def escalation_overview(self, db: Session, owner_id: int) -> dict:
        rows = db.execute(
            select(SupportEscalation.status, func.count())
            .where(SupportEscalation.owner_id == owner_id)
            .group_by(SupportEscalation.status)
        ).all()
        by_status: dict[str, int] = {}
        for status, count in rows:
            try:
                by_status[str(status)] = int(count)
            except (TypeError, ValueError):
                by_status[str(status)] = 0
        total = sum(by_status.values())

        def _count(statement) -> int:
            value = db.scalar(statement)
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "total": total,
            "pending": by_status.get("pending", 0),
            "accepted": by_status.get("accepted", 0),
            "resolved": by_status.get("resolved", 0),
            "returned": by_status.get("returned", 0),
            "highRisk": _count(
                select(func.count(SupportEscalation.id)).where(
                    SupportEscalation.owner_id == owner_id,
                    SupportEscalation.risk_level == "high",
                    SupportEscalation.status.in_(("pending", "accepted")),
                )
            ),
            "byCategory": {
                category: _count(
                    select(func.count(SupportEscalation.id)).where(
                        SupportEscalation.owner_id == owner_id,
                        SupportEscalation.category == category,
                    )
                )
                for category in sorted(ESCALATION_CATEGORIES)
            },
        }

    def evaluation_overview(self, db: Session, owner_id: int) -> dict:
        datasets = list(
            db.scalars(
                select(EvaluationDataset).where(EvaluationDataset.owner_id == owner_id)
            )
        )
        runs = list(
            db.scalars(
                select(EvaluationRun)
                .where(EvaluationRun.owner_id == owner_id)
                .order_by(EvaluationRun.id.desc())
            )
        )
        run_items = []
        for run in runs:
            results = list(
                db.scalars(
                    select(EvaluationResult).where(EvaluationResult.run_id == run.id)
                )
            )
            payloads = [_json(item.evidence_json, {}) for item in results]
            totals: list[int] = []
            for raw in (
                item.get("metrics", {}).get("total_score") for item in payloads
            ):
                try:
                    if isinstance(raw, (int, float)):
                        totals.append(int(raw))
                except (TypeError, ValueError):
                    continue
            score = (
                round(sum(totals) / len(totals), 1)
                if totals
                else (
                    round(
                        sum(item.expected_point_score for item in results)
                        / len(results),
                        1,
                    )
                    if results
                    else None
                )
            )
            risky = sum(1 for item in payloads if item.get("gateBlocked"))
            modes = sorted(
                {
                    str(item.get("runtimeMode"))
                    for item in payloads
                    if item.get("runtimeMode")
                }
            )
            run_items.append(
                {
                    "id": run.id,
                    "status": run.status,
                    "score": score,
                    "caseCount": len(results),
                    "highRiskFailures": risky,
                    "gate": "blocked" if risky else "passed",
                    "runtimeModes": modes,
                    "startedAt": run.started_at.isoformat(),
                    "isDemo": run.is_demo,
                }
            )
        return {
            "datasetCount": len(datasets),
            "evaluationCaseCount": sum(len(item.cases) for item in datasets),
            "runs": run_items,
            "provenance": "demo"
            if datasets and all(item.is_demo for item in datasets)
            else "production",
        }

    def evaluation_detail(self, db: Session, owner_id: int, run_id: int) -> dict:
        run = db.scalar(
            select(EvaluationRun).where(
                EvaluationRun.id == run_id, EvaluationRun.owner_id == owner_id
            )
        )
        if run is None:
            raise AppError("EVALUATION_RUN_NOT_FOUND", "评测运行不存在", 404)
        dataset = db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.id == run.dataset_id,
                EvaluationDataset.owner_id == owner_id,
            )
        )
        if dataset is None:
            raise AppError("EVALUATION_DATASET_NOT_FOUND", "评测集不存在", 404)
        cases = {item.id: item for item in dataset.cases}
        results = list(
            db.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.run_id == run.id)
                .order_by(EvaluationResult.id)
            )
        )
        return {
            "id": run.id,
            "status": run.status,
            "datasetId": dataset.id,
            "datasetName": dataset.name,
            "config": _json(run.config_snapshot_json, {}),
            "error": run.error_summary,
            "startedAt": run.started_at.isoformat(),
            "completedAt": run.completed_at.isoformat() if run.completed_at else None,
            "results": [
                {
                    "id": item.id,
                    "caseId": item.case_id,
                    "caseKey": cases[item.case_id].case_key
                    if item.case_id in cases
                    else None,
                    "answer": item.answer,
                    "expectedPointScore": item.expected_point_score,
                    "citationCorrect": item.citation_correct,
                    "refusalCorrect": item.refusal_correct,
                    "latencyMs": item.latency_ms,
                    **_json(item.evidence_json, {}),
                }
                for item in results
            ],
        }

    async def run_evaluation_async(
        self,
        db: Session,
        owner_id: int,
        actor_id: int,
        release_id: int,
        coordinator: AgenticRagCoordinator,
    ) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError(
                "KNOWLEDGE_RELEASE_NOT_PUBLISHED", "评测候选必须是已发布版本", 409
            )
        dataset = db.scalar(
            select(EvaluationDataset)
            .where(EvaluationDataset.owner_id == owner_id)
            .order_by(EvaluationDataset.id)
            .limit(1)
        )
        if dataset is None:
            raise AppError("EVALUATION_DATASET_NOT_FOUND", "尚未配置评测集", 409)
        run = EvaluationRun(
            owner_id=owner_id,
            dataset_id=dataset.id,
            status="running",
            config_snapshot_json=json.dumps(
                {
                    "knowledgeReleaseId": release.id,
                    "knowledgeVersion": release.version,
                    "scoring": SCORING_VERSION,
                }
            ),
            started_at=datetime.utcnow(),
            is_demo=dataset.is_demo,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()
        runner = AgentEvaluationRunner(coordinator)
        try:
            for case in dataset.cases:
                try:
                    execution = await asyncio.wait_for(
                        runner.execute_case(db, owner_id=owner_id, case=case),
                        timeout=120,
                    )
                except asyncio.TimeoutError:
                    # 单用例超时：记录失败结果，继续下一个，避免整个评测永久 running
                    db.add(
                        EvaluationResult(
                            run_id=run.id,
                            case_id=case.id,
                            answer="",
                            expected_point_score=0,
                            citation_correct=False,
                            refusal_correct=False,
                            latency_ms=120000,
                            evidence_json=json.dumps(
                                {
                                    "releaseId": release.id,
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
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    continue
                db.add(
                    EvaluationResult(
                        run_id=run.id,
                        case_id=case.id,
                        answer=execution.answer,
                        expected_point_score=execution.metrics.expected_point_score,
                        citation_correct=execution.metrics.citation_correct,
                        refusal_correct=execution.metrics.refusal_correct,
                        latency_ms=execution.latency_ms,
                        evidence_json=json.dumps(
                            execution_payload(execution, release_id=release.id),
                            ensure_ascii=False,
                        ),
                    )
                )
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            db.commit()
        except Exception as exc:
            db.rollback()
            persisted = db.get(EvaluationRun, run_id)
            if persisted is not None:
                persisted.status = "failed"
                persisted.error_summary = type(exc).__name__
                persisted.completed_at = datetime.utcnow()
                db.commit()
            raise
        return self.evaluation_overview(db, owner_id)["runs"][0]

    def run_evaluation(
        self,
        db: Session,
        owner_id: int,
        actor_id: int,
        release_id: int,
        coordinator: AgenticRagCoordinator | None = None,
    ) -> dict:
        """Compatibility wrapper for CLI/tests outside an async request."""
        return asyncio.run(
            self.run_evaluation_async(
                db,
                owner_id,
                actor_id,
                release_id,
                coordinator or AgenticRagCoordinator(None, None),
            )
        )

    def decide_release(
        self,
        db: Session,
        owner_id: int,
        actor_id: int,
        run_id: int,
        release_id: int,
        decision: str,
    ) -> dict:
        if decision not in {"approved", "rejected"}:
            raise AppError("INVALID_RELEASE_DECISION", "不支持的上线决策", 422)
        run = db.scalar(
            select(EvaluationRun).where(
                EvaluationRun.id == run_id, EvaluationRun.owner_id == owner_id
            )
        )
        release = self._require_release(db, owner_id, release_id)
        if run is None:
            raise AppError("EVALUATION_RUN_NOT_FOUND", "评测运行不存在", 404)
        results = list(
            db.scalars(
                select(EvaluationResult).where(EvaluationResult.run_id == run.id)
            )
        )
        config = _json(run.config_snapshot_json, {})
        if config.get("knowledgeReleaseId") != release.id:
            raise AppError(
                "EVALUATION_RELEASE_MISMATCH", "评测运行与候选知识版本不匹配", 409
            )
        risky = sum(
            1 for item in results if _json(item.evidence_json, {}).get("gateBlocked")
        )
        if decision == "approved" and risky:
            raise AppError("HIGH_RISK_GATE_BLOCKED", "高风险用例未通过，禁止上线", 409)
        item = SupportReleaseDecision(
            owner_id=owner_id,
            evaluation_run_id=run.id,
            knowledge_release_id=release.id,
            actor_id=actor_id,
            decision=decision,
            gate_snapshot_json=json.dumps(
                {
                    "highRiskFailures": risky,
                    "caseCount": len(results),
                    "scoringVersion": SCORING_VERSION,
                }
            ),
        )
        db.add(item)
        if decision == "approved":
            for active in db.scalars(
                select(KnowledgeRelease).where(
                    KnowledgeRelease.owner_id == owner_id,
                    KnowledgeRelease.is_active.is_(True),
                )
            ):
                active.is_active = False
            release.is_active = True
        db.commit()
        return {
            "id": item.id,
            "decision": decision,
            "highRiskFailures": risky,
            "releaseId": release.id,
            "runId": run.id,
        }

    def _require_release(
        self, db: Session, owner_id: int, release_id: int
    ) -> KnowledgeRelease:
        item = db.scalar(
            select(KnowledgeRelease).where(
                KnowledgeRelease.id == release_id, KnowledgeRelease.owner_id == owner_id
            )
        )
        if item is None:
            raise AppError("KNOWLEDGE_RELEASE_NOT_FOUND", "知识版本不存在", 404)
        return item

    @staticmethod
    def _release(db: Session, item: KnowledgeRelease) -> dict:
        documents = list(
            db.scalars(
                select(KnowledgeReleaseDocument)
                .where(KnowledgeReleaseDocument.release_id == item.id)
                .order_by(KnowledgeReleaseDocument.id)
            )
        )
        return {
            "id": item.id,
            "version": item.version,
            "title": item.title,
            "status": item.status,
            "processingStatus": item.processing_status,
            "retrievalMode": item.retrieval_mode,
            "isActive": item.is_active,
            "isDemo": item.is_demo,
            "contentHash": item.content_hash,
            "publishedAt": item.published_at.isoformat() if item.published_at else None,
            "documents": [
                {
                    "id": document.document_id,
                    "filename": document.filename_snapshot,
                    "hash": document.document_hash,
                }
                for document in documents
            ],
        }

    @staticmethod
    def _case_summary(db: Session, item: SupportCase) -> dict:
        last_message = db.scalar(
            select(SupportMessage.content)
            .where(SupportMessage.case_id == item.id)
            .order_by(SupportMessage.id.desc())
            .limit(1)
        )
        return {
            "id": item.id,
            "caseKey": item.case_key,
            "customerName": item.customer_name,
            "channel": item.customer_channel,
            "subject": item.subject,
            "status": item.status,
            "priority": item.priority,
            "assigneeId": item.assignee_id,
            "labels": _json(item.labels_json, []),
            "unread": item.unread,
            "version": item.version,
            "isDemo": item.is_demo,
            "lastMessage": last_message,
            "updatedAt": item.updated_at.isoformat(),
        }

    @staticmethod
    def _suggestion(item: ReplySuggestion, decision: ReplyDecision | None) -> dict:
        snapshot = _json(item.config_snapshot_json, {})
        return {
            "id": item.id,
            "status": item.status,
            "content": item.content,
            "citations": _json(item.citations_json, []),
            "riskFlags": _json(item.risk_flags_json, []),
            "modelId": item.model_id,
            "promptVersion": item.prompt_version,
            "knowledgeReleaseId": item.knowledge_release_id,
            "latencyMs": item.latency_ms,
            "errorCode": item.error_code,
            "runtimeMode": snapshot.get("runtimeMode"),
            "terminalState": snapshot.get("terminalState"),
            "resolution": snapshot.get("resolution"),
            "decision": decision.decision if decision else None,
            "finalContent": decision.final_content if decision else None,
            "createdAt": item.created_at.isoformat(),
        }

    @staticmethod
    def _outbound(item: OutboundMessage) -> dict:
        return {
            "id": item.id,
            "channel": item.channel,
            "status": item.status,
            "externalId": item.external_id,
            "failureReason": item.failure_reason,
            "isDemo": item.is_demo,
            "deliveryClaim": "simulated" if item.is_demo else "external-status",
            "createdAt": item.created_at.isoformat(),
            "sentAt": item.sent_at.isoformat() if item.sent_at else None,
            "deliveredAt": item.delivered_at.isoformat() if item.delivered_at else None,
        }

    @staticmethod
    def _citation(
        chunk: KnowledgeChunk,
        document: KnowledgeDocument,
        release_version: str,
        index: int,
    ) -> dict:
        """Return one citation contract shared by support UI and source preview."""
        content = _without_frontmatter(chunk.content)[:260]
        return {
            "index": index,
            "chunkId": chunk.id,
            "documentId": document.id,
            "docId": str(document.id),
            "docName": document.source_title or document.filename,
            "content": content,
            "excerpt": content,
            "releaseVersion": release_version,
            "sourceType": "url" if document.source_url else "file",
            "url": document.source_url,
            "canonicalUrl": document.source_url,
            "publisher": document.source_publisher,
            "retrievedAt": (
                document.source_retrieved_at.isoformat()
                if document.source_retrieved_at
                else None
            ),
            "applicability": _json(document.applicability_json, []),
            "exclusions": _json(document.exclusions_json, []),
            "reviewStatus": document.review_status,
            "contentOrigin": document.content_origin,
        }

    @staticmethod
    def _evidence_citation(item, index: int) -> dict:
        """把 Agent Runtime 返回的 policy 证据转成与旧版一致的 citation 契约。"""
        meta = item.metadata or {}
        content = _without_frontmatter(item.content)[:260]
        doc_id = meta.get("document_id") or meta.get("chunk_id")
        doc_name = (
            meta.get("document_name")
            or meta.get("doc_name")
            or meta.get("source_title")
            or meta.get("source")
            or item.source
            or "知识文档"
        )
        canonical_url = meta.get("canonicalUrl") or meta.get("canonical_url")
        retrieved_at = (
            meta.get("retrievedAt")
            or meta.get("retrieved_at")
            or meta.get("retrieval_date")
        )
        return {
            "index": index,
            "chunkId": meta.get("chunk_id") or meta.get("chunkId"),
            "documentId": meta.get("document_id") or meta.get("documentId"),
            "docId": str(doc_id) if doc_id is not None else None,
            "docName": doc_name,
            "content": content,
            "excerpt": content,
            "releaseVersion": meta.get("release_version") or meta.get("releaseVersion"),
            "sourceType": "url" if (canonical_url or "").startswith("http") else "file",
            "url": canonical_url,
            "canonicalUrl": canonical_url,
            "publisher": meta.get("publisher"),
            "retrievedAt": retrieved_at,
            "applicability": meta.get("applicability", []),
            "exclusions": meta.get("exclusions", []),
            "reviewStatus": meta.get("review_status") or meta.get("reviewStatus"),
            "contentOrigin": meta.get("provenance") or meta.get("content_origin"),
        }

    @staticmethod
    def _compose_draft(run, question: str, order_no: str | None) -> str:
        """生成简短、可直接发送给顾客的草稿，不混入内部证据原文。"""
        intent = run.review_details.intent.lower()
        topic = "退款" if "refund" in intent else "售后"
        order_context = f"关于订单 {order_no}，" if order_no else ""
        draft = (
            f"您好，{order_context}您反馈的{topic}问题我们已收到并完成初步核实。"
            "我们会依据实际情况和适用规则继续处理，并尽快向您同步结果。"
            "如还需补充凭证或信息，我们会及时联系您，感谢您的理解与配合。"
        )
        return draft[:320]

    @staticmethod
    def _build_resolution(
        run, question: str, order_no: str | None, risk_flags: list[str]
    ) -> dict:
        """从 AgenticRun 派生结构化处理决议（intent/risk/facts/actions/canSend）。"""
        details = run.review_details
        facts = []
        missing = list(details.missing_fields or ())
        for item in run.results:
            meta = item.metadata or {}
            fact_type = meta.get("factType")
            if fact_type in (None, "policy"):
                continue
            facts.append(
                {
                    "type": fact_type,
                    "content": item.content[:200],
                    "orderNo": meta.get("orderNo"),
                }
            )
        can_send = run.terminal_state == "grounded" and details.decision == "ready"
        actions = ["告知顾客当前已核实的状态与预计时间"]
        if can_send:
            actions.append("按建议草稿回复顾客")
        else:
            actions.append("转人工复核后再发送")
        if risk_flags or details.risk in {"medium", "high"}:
            actions.append(
                "风险项需人工审核：" + "、".join(risk_flags or [details.risk])
            )
        return {
            "intent": details.intent,
            "risk": details.risk,
            "facts": facts,
            "missingFacts": missing,
            "recommendedActions": actions,
            "draftReply": SupportService._compose_draft(run, question, order_no),
            "citations": [
                item.content[:260]
                for item in run.results
                if item.metadata.get("factType") in (None, "policy")
            ][:4],
            "canSend": can_send,
            "escalationReason": None if can_send else details.summary,
            "terminalState": run.terminal_state,
        }

    @staticmethod
    def _event(
        db: Session,
        case: SupportCase,
        actor_id: int | None,
        event_type: str,
        payload: dict,
    ) -> None:
        db.add(
            SupportEvent(
                owner_id=case.owner_id,
                case_id=case.id,
                actor_id=actor_id,
                event_type=event_type,
                payload_json=json.dumps(payload, ensure_ascii=False),
                is_demo=case.is_demo,
            )
        )
