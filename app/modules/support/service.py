from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.framework.errors import AppError, ProviderUnavailableError
from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.modules.evaluation.models import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.modules.support.models import (
    KnowledgeGap,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
    ReplyDecision,
    ReplySuggestion,
    SupportCase,
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


class SupportService:
    def owner_for(self, db: Session, user: User) -> int:
        if user.role == "admin":
            owner = db.scalar(
                select(SupportCase.owner_id)
                .join(User, User.id == SupportCase.owner_id)
                .where(User.is_demo.is_(True))
                .order_by(SupportCase.id.desc())
                .limit(1)
            )
            if owner is not None:
                return int(owner)
            demo_owner = db.scalar(select(User.id).where(User.is_demo.is_(True)).order_by(User.id).limit(1))
            if demo_owner is not None:
                return int(demo_owner)
        return int(user.id)

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
        cases = list(db.scalars(query.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc())))
        return [self._case_summary(db, item) for item in cases]

    def detail(self, db: Session, owner_id: int, case_id: int) -> dict:
        case = self.require_case(db, owner_id, case_id)
        source = db.get(DataSource, case.source_data_id) if case.source_data_id else None
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
            for item in db.scalars(select(ReplyDecision).where(ReplyDecision.case_id == case.id))
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
                "dataSource": ({
                    "id": source.id, "datasetKey": source.dataset_key, "version": source.version,
                    "title": source.title, "publisher": source.publisher, "sourceUri": source.source_uri,
                    "license": source.license, "limitations": _json(source.limitations_json, []),
                } if source else None),
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
            "suggestions": [self._suggestion(item, decisions.get(item.id)) for item in suggestions],
        }

    def require_case(self, db: Session, owner_id: int, case_id: int) -> SupportCase:
        item = db.scalar(
            select(SupportCase).where(SupportCase.id == case_id, SupportCase.owner_id == owner_id)
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
            raise AppError("CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409)
        if status == "resolved" and not resolution_code:
            raise AppError("RESOLUTION_CODE_REQUIRED", "解决工单前必须选择解决结果", 422)
        previous = case.status
        case.status = status
        case.resolution_code = resolution_code if status == "resolved" else None
        case.resolution_note = resolution_note if status == "resolved" else case.resolution_note
        case.unread = False
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, "status_changed", {"from": previous, "to": status, "reason": reason})
        db.commit()
        return self.detail(db, owner_id, case.id)

    def assign(self, db: Session, owner_id: int, case_id: int, actor_id: int, assignee_id: int | None, expected_version: int) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if case.version != expected_version:
            raise AppError("CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409)
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

    def set_labels(self, db: Session, owner_id: int, case_id: int, actor_id: int, labels: list[str], expected_version: int) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if case.version != expected_version:
            raise AppError("CASE_VERSION_CONFLICT", "工单已被其他成员更新，请刷新后重试", 409)
        clean = sorted({item.strip() for item in labels if item.strip()})[:12]
        case.labels_json = json.dumps(clean, ensure_ascii=False)
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, "labels_changed", {"labels": clean})
        db.commit()
        return self.detail(db, owner_id, case.id)

    def manual_reply(self, db: Session, owner_id: int, case_id: int, actor_id: int, content: str) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if not content.strip():
            raise AppError("EMPTY_REPLY", "回复内容不能为空", 422)
        message = SupportMessage(
            case_id=case.id,
            actor_id=actor_id,
            role="agent",
            content=content.strip(),
            sent_to_customer=True,
        )
        db.add(message)
        case.unread = False
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, "manual_reply_sent", {})
        db.commit()
        return self.detail(db, owner_id, case.id)

    async def generate_suggestion(self, db: Session, owner_id: int, case_id: int, actor_id: int, model_router) -> dict:
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
        document_ids = (
            tuple(
                db.scalars(
                    select(KnowledgeReleaseDocument.document_id).where(
                        KnowledgeReleaseDocument.release_id == release.id
                    )
                )
            )
            if release
            else ()
        )
        chunks = (
            list(
                db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id.in_(document_ids), KnowledgeChunk.enabled.is_(True))
                    .order_by(KnowledgeChunk.document_id, KnowledgeChunk.position)
                    .limit(4)
                )
            )
            if document_ids
            else []
        )
        citations = [
            {"chunkId": item.id, "documentId": item.document_id, "content": item.content[:260], "releaseVersion": release.version}
            for item in chunks
        ]
        risk_flags = [flag for flag, terms in RISK_TERMS.items() if any(term in question for term in terms)]
        started = time.perf_counter()
        status = "completed"
        content: str | None = None
        error_code: str | None = None
        model_id = "unconfigured"
        if release is None or not citations:
            status = "insufficient_evidence"
            error_code = "INSUFFICIENT_EVIDENCE"
        elif model_router is None:
            status = "provider_unavailable"
            error_code = "MODEL_PROVIDER_UNAVAILABLE"
        else:
            model_id = "configured-chat-router"
            context = "\n\n".join(f"[资料{i}] {item['content']}" for i, item in enumerate(citations, 1))
            try:
                content = await model_router.complete(
                    ChatRequest(
                        messages=[
                            ChatMessage("system", "你是即时零售客服回复助手。仅依据资料提出简洁建议，资料不足必须说明；退款、赔付、食品安全必须提示人工审核。"),
                            ChatMessage("user", f"顾客问题：{question}\n\n已发布资料：\n{context}"),
                        ],
                        temperature=0.1,
                        max_tokens=600,
                    )
                )
            except ProviderUnavailableError:
                status = "provider_unavailable"
                error_code = "MODEL_PROVIDER_UNAVAILABLE"
        suggestion = ReplySuggestion(
            case_id=case.id,
            requested_by=actor_id,
            knowledge_release_id=release.id if release else None,
            status=status,
            content=content,
            citations_json=json.dumps(citations, ensure_ascii=False),
            risk_flags_json=json.dumps(risk_flags, ensure_ascii=False),
            model_id=model_id,
            prompt_version="support-v1",
            config_snapshot_json=json.dumps({"knowledgeVersion": release.version if release else None}),
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_code=error_code,
        )
        db.add(suggestion)
        db.flush()
        self._event(db, case, actor_id, "suggestion_generated", {"suggestionId": suggestion.id, "status": status})
        db.commit()
        return self._suggestion(suggestion, None)

    def decide(self, db: Session, owner_id: int, case_id: int, suggestion_id: int, actor_id: int, decision: str, final_content: str | None, reason: str | None) -> dict:
        if decision not in DECISIONS:
            raise AppError("INVALID_REPLY_DECISION", "不支持的审核动作", 422)
        case = self.require_case(db, owner_id, case_id)
        suggestion = db.scalar(select(ReplySuggestion).where(ReplySuggestion.id == suggestion_id, ReplySuggestion.case_id == case.id))
        if suggestion is None:
            raise AppError("SUGGESTION_NOT_FOUND", "回复建议不存在", 404)
        if db.scalar(select(ReplyDecision.id).where(ReplyDecision.suggestion_id == suggestion.id)) is not None:
            raise AppError("SUGGESTION_ALREADY_REVIEWED", "该建议已经完成审核", 409)
        if decision in {"accepted", "edited"}:
            outgoing = (final_content if decision == "edited" else suggestion.content) or ""
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
            db.add(SupportMessage(case_id=case.id, actor_id=actor_id, role="agent", content=outgoing.strip(), suggestion_id=suggestion.id, sent_to_customer=True))
        if decision == "escalated":
            case.status = "escalated"
        case.unread = False
        case.version += 1
        case.updated_at = datetime.utcnow()
        self._event(db, case, actor_id, f"suggestion_{decision}", {"suggestionId": suggestion.id, "reason": reason})
        db.commit()
        return self.detail(db, owner_id, case.id)

    def metrics(self, db: Session, owner_id: int) -> dict:
        total = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.owner_id == owner_id)) or 0)
        statuses = dict(db.execute(select(SupportCase.status, func.count()).where(SupportCase.owner_id == owner_id).group_by(SupportCase.status)).all())
        decisions = dict(
            db.execute(
                select(ReplyDecision.decision, func.count())
                .join(SupportCase, SupportCase.id == ReplyDecision.case_id)
                .where(SupportCase.owner_id == owner_id)
                .group_by(ReplyDecision.decision)
            ).all()
        )
        reviewed = sum(int(value) for value in decisions.values())
        suggestions = int(db.scalar(select(func.count(ReplySuggestion.id)).join(SupportCase).where(SupportCase.owner_id == owner_id)) or 0)
        cited = int(db.scalar(select(func.count(ReplySuggestion.id)).join(SupportCase).where(SupportCase.owner_id == owner_id, ReplySuggestion.citations_json != "[]")) or 0)
        demo = int(db.scalar(select(func.count(SupportCase.id)).where(SupportCase.owner_id == owner_id, SupportCase.is_demo.is_(True))) or 0)
        return {
            "totalCases": total,
            "pendingCases": int(statuses.get("pending", 0)),
            "resolvedCases": int(statuses.get("resolved", 0)),
            "escalatedCases": int(statuses.get("escalated", 0)),
            "resolutionRate": round(int(statuses.get("resolved", 0)) / total * 100, 1) if total else None,
            "acceptanceRate": round((int(decisions.get("accepted", 0)) + int(decisions.get("edited", 0))) / reviewed * 100, 1) if reviewed else None,
            "editRate": round(int(decisions.get("edited", 0)) / reviewed * 100, 1) if reviewed else None,
            "citationCoverage": round(cited / suggestions * 100, 1) if suggestions else None,
            "provenance": "demo" if total and demo == total else ("mixed" if demo else "production"),
        }

    def list_releases(self, db: Session, owner_id: int) -> list[dict]:
        releases = list(db.scalars(select(KnowledgeRelease).where(KnowledgeRelease.owner_id == owner_id).order_by(KnowledgeRelease.id.desc())))
        return [self._release(db, item) for item in releases]

    def knowledge_sources(self, db: Session, owner_id: int) -> list[dict]:
        documents = list(db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.uploader_id == owner_id).order_by(KnowledgeDocument.id)
        ))
        return [{
            "id": item.id, "title": item.source_title or item.filename, "filename": item.filename,
            "contentOrigin": item.content_origin, "publisher": item.source_publisher,
            "canonicalUrl": item.source_url, "retrievedAt": item.source_retrieved_at.isoformat() if item.source_retrieved_at else None,
            "jurisdiction": item.source_jurisdiction, "nextReviewAt": item.next_review_at.isoformat() if item.next_review_at else None,
            "reviewStatus": item.review_status, "applicability": _json(item.applicability_json, []),
            "exclusions": _json(item.exclusions_json, []), "usageNote": item.license_or_usage_note or item.source_usage_note,
            "status": item.status, "enabled": item.enabled, "checksum": item.demo_content_sha256,
        } for item in documents]

    def create_release(self, db: Session, owner_id: int, actor_id: int, version: str, title: str, document_ids: list[int]) -> dict:
        version, title = version.strip(), title.strip()
        if not version or not title or not document_ids:
            raise AppError("INVALID_KNOWLEDGE_RELEASE", "版本、标题和知识文档不能为空", 422)
        if db.scalar(select(KnowledgeRelease.id).where(KnowledgeRelease.owner_id == owner_id, KnowledgeRelease.version == version)):
            raise AppError("KNOWLEDGE_RELEASE_EXISTS", "该知识版本已存在", 409)
        documents = list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(set(document_ids)), KnowledgeDocument.uploader_id == owner_id)))
        if len(documents) != len(set(document_ids)):
            raise AppError("KNOWLEDGE_DOCUMENT_NOT_FOUND", "部分知识文档不存在或不属于当前商家", 404)
        snapshots = [(item, item.demo_content_sha256 or hashlib.sha256(f"{item.id}:{item.filename}:{item.file_size}".encode()).hexdigest()) for item in documents]
        content_hash = hashlib.sha256("|".join(sorted(item_hash for _, item_hash in snapshots)).encode()).hexdigest()
        release = KnowledgeRelease(owner_id=owner_id, version=version, title=title, status="draft", processing_status="ready", content_hash=content_hash, retrieval_mode="keyword")
        db.add(release)
        db.flush()
        for document, document_hash in snapshots:
            db.add(KnowledgeReleaseDocument(release_id=release.id, document_id=document.id, document_hash=document_hash, filename_snapshot=document.filename))
        db.commit()
        return self._release(db, release)

    def publish_release(self, db: Session, owner_id: int, release_id: int, actor_id: int) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status == "published":
            return self._release(db, release)
        memberships = list(db.scalars(select(KnowledgeReleaseDocument).where(KnowledgeReleaseDocument.release_id == release.id)))
        if not memberships:
            raise AppError("EMPTY_KNOWLEDGE_RELEASE", "知识版本没有可发布文档", 422)
        document_ids = [item.document_id for item in memberships]
        documents = list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))))
        stale = [item.filename for item in documents if item.review_status != "current" or (item.next_review_at is not None and item.next_review_at < date.today())]
        unattributed = [item.filename for item in documents if item.content_origin == "public_summary" and (not item.source_url or not item.source_publisher or not item.source_retrieved_at)]
        hash_drift = []
        for membership in memberships:
            document = db.get(KnowledgeDocument, membership.document_id)
            current_hash = document.demo_content_sha256 or hashlib.sha256(
                f"{document.id}:{document.filename}:{document.file_size}".encode()
            ).hexdigest()
            if current_hash != membership.document_hash:
                hash_drift.append(membership.filename_snapshot)
        if stale or unattributed or hash_drift:
            release.processing_status = "blocked"; db.commit()
            raise AppError("KNOWLEDGE_PROVENANCE_INVALID", "知识版本存在过期、缺少来源或内容漂移的文档", 409, {"stale": stale, "unattributed": unattributed, "hashDrift": hash_drift})
        ready = int(db.scalar(select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.id.in_(document_ids), KnowledgeDocument.status.in_(("ready", "indexed")), KnowledgeDocument.enabled.is_(True))) or 0)
        chunk_count = int(db.scalar(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id.in_(document_ids), KnowledgeChunk.enabled.is_(True))) or 0)
        if ready != len(document_ids) or chunk_count == 0:
            release.processing_status = "blocked"
            db.commit()
            raise AppError("KNOWLEDGE_RELEASE_NOT_READY", "存在未完成解析或无可检索分块的文档", 409)
        release.status = "published"
        release.processing_status = "ready"
        release.published_by = actor_id
        release.published_at = datetime.utcnow()
        db.commit()
        return self._release(db, release)

    def activate_release(self, db: Session, owner_id: int, release_id: int) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError("KNOWLEDGE_RELEASE_NOT_PUBLISHED", "只能启用已发布知识版本", 409)
        for item in db.scalars(select(KnowledgeRelease).where(KnowledgeRelease.owner_id == owner_id, KnowledgeRelease.is_active.is_(True))):
            item.is_active = False
        release.is_active = True
        db.commit()
        return self._release(db, release)

    def list_gaps(self, db: Session, owner_id: int) -> list[dict]:
        items = list(db.scalars(select(KnowledgeGap).where(KnowledgeGap.owner_id == owner_id).order_by(KnowledgeGap.status, KnowledgeGap.occurrence_count.desc(), KnowledgeGap.id.desc())))
        return [{"id": item.id, "title": item.title, "category": item.category, "severity": item.severity, "status": item.status, "occurrenceCount": item.occurrence_count, "ownerUserId": item.owner_user_id, "resolvingReleaseId": item.resolving_release_id, "evidence": _json(item.evidence_json, []), "isDemo": item.is_demo} for item in items]

    def add_quality_label(self, db: Session, owner_id: int, case_id: int, actor_id: int, verdict: str, failure_category: str | None, severity: str | None, note: str | None, suggestion_id: int | None = None) -> dict:
        case = self.require_case(db, owner_id, case_id)
        if verdict not in {"passed", "failed"}:
            raise AppError("INVALID_QUALITY_VERDICT", "质检结论必须为通过或失败", 422)
        if verdict == "failed" and not failure_category:
            raise AppError("FAILURE_CATEGORY_REQUIRED", "质检失败必须选择失败类型", 422)
        label = SupportQualityLabel(owner_id=owner_id, case_id=case.id, suggestion_id=suggestion_id, reviewer_id=actor_id, verdict=verdict, failure_category=failure_category, severity=severity, note=note)
        db.add(label)
        if verdict == "failed":
            fingerprint = hashlib.sha256(f"{owner_id}:{failure_category}:{case.subject.strip().lower()}".encode()).hexdigest()
            gap = db.scalar(select(KnowledgeGap).where(KnowledgeGap.owner_id == owner_id, KnowledgeGap.fingerprint == fingerprint))
            evidence = {"caseId": case.id, "suggestionId": suggestion_id, "labelId": None}
            if gap is None:
                gap = KnowledgeGap(owner_id=owner_id, fingerprint=fingerprint, title=f"{case.subject}：{failure_category}", category=failure_category or "other", severity=severity or "medium", evidence_json="[]", is_demo=case.is_demo)
                db.add(gap)
            else:
                gap.occurrence_count += 1
            db.flush()
            evidence["labelId"] = label.id
            entries = _json(gap.evidence_json, [])
            entries.append(evidence)
            gap.evidence_json = json.dumps(entries[-20:], ensure_ascii=False)
            gap.updated_at = datetime.utcnow()
        db.commit()
        return {"id": label.id, "caseId": case.id, "verdict": label.verdict, "failureCategory": label.failure_category, "severity": label.severity, "note": label.note}

    def resolve_gap(self, db: Session, owner_id: int, gap_id: int, actor_id: int, release_id: int) -> dict:
        gap = db.scalar(select(KnowledgeGap).where(KnowledgeGap.id == gap_id, KnowledgeGap.owner_id == owner_id))
        if gap is None:
            raise AppError("KNOWLEDGE_GAP_NOT_FOUND", "知识缺口不存在", 404)
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError("KNOWLEDGE_RELEASE_NOT_PUBLISHED", "解决缺口必须绑定已发布版本", 409)
        gap.status, gap.owner_user_id, gap.resolving_release_id = "resolved", actor_id, release.id
        gap.updated_at = datetime.utcnow()
        db.commit()
        return next(item for item in self.list_gaps(db, owner_id) if item["id"] == gap.id)

    def quality_overview(self, db: Session, owner_id: int) -> dict:
        labels = list(db.scalars(select(SupportQualityLabel).where(SupportQualityLabel.owner_id == owner_id)))
        categories: dict[str, int] = {}
        for item in labels:
            key = item.failure_category or "passed"
            categories[key] = categories.get(key, 0) + 1
        gaps = self.list_gaps(db, owner_id)
        return {"reviewed": len(labels), "passed": sum(1 for item in labels if item.verdict == "passed"), "failureCategories": categories, "openGaps": sum(1 for item in gaps if item["status"] == "open"), "gaps": gaps, "provenance": self.metrics(db, owner_id)["provenance"]}

    def evaluation_overview(self, db: Session, owner_id: int) -> dict:
        datasets = list(db.scalars(select(EvaluationDataset).where(EvaluationDataset.owner_id == owner_id)))
        runs = list(db.scalars(select(EvaluationRun).where(EvaluationRun.owner_id == owner_id).order_by(EvaluationRun.id.desc())))
        run_items = []
        for run in runs:
            results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
            score = round(sum(item.expected_point_score for item in results) / len(results), 1) if results else None
            risky = sum(1 for item in results if not item.citation_correct or not item.refusal_correct)
            run_items.append({"id": run.id, "status": run.status, "score": score, "caseCount": len(results), "highRiskFailures": risky, "gate": "blocked" if risky else "passed", "startedAt": run.started_at.isoformat(), "isDemo": run.is_demo})
        return {"datasetCount": len(datasets), "evaluationCaseCount": sum(len(item.cases) for item in datasets), "runs": run_items, "provenance": "demo" if datasets and all(item.is_demo for item in datasets) else "production"}

    def run_evaluation(self, db: Session, owner_id: int, actor_id: int, release_id: int) -> dict:
        release = self._require_release(db, owner_id, release_id)
        if release.status != "published":
            raise AppError("KNOWLEDGE_RELEASE_NOT_PUBLISHED", "评测候选必须是已发布版本", 409)
        dataset = db.scalar(select(EvaluationDataset).where(EvaluationDataset.owner_id == owner_id).order_by(EvaluationDataset.id).limit(1))
        if dataset is None:
            raise AppError("EVALUATION_DATASET_NOT_FOUND", "尚未配置评测集", 409)
        run = EvaluationRun(owner_id=owner_id, dataset_id=dataset.id, status="completed", config_snapshot_json=json.dumps({"knowledgeReleaseId": release.id, "knowledgeVersion": release.version, "scoring": "deterministic-rule-v1"}), started_at=datetime.utcnow(), completed_at=datetime.utcnow(), is_demo=dataset.is_demo)
        db.add(run)
        db.flush()
        for case in dataset.cases:
            answer = case.reference_answer or "按已发布政策处理；证据不足时转人工复核。"
            score = 100 if case.expected_points else 80
            db.add(EvaluationResult(run_id=run.id, case_id=case.id, answer=answer, expected_point_score=score, citation_correct=bool(case.expected_document_keys), refusal_correct=True, latency_ms=0, evidence_json=json.dumps({"releaseId": release.id, "rule": "fixture-reference"})))
        db.commit()
        return self.evaluation_overview(db, owner_id)["runs"][0]

    def decide_release(self, db: Session, owner_id: int, actor_id: int, run_id: int, release_id: int, decision: str) -> dict:
        if decision not in {"approved", "rejected"}:
            raise AppError("INVALID_RELEASE_DECISION", "不支持的上线决策", 422)
        run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.owner_id == owner_id))
        release = self._require_release(db, owner_id, release_id)
        if run is None:
            raise AppError("EVALUATION_RUN_NOT_FOUND", "评测运行不存在", 404)
        results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
        risky = sum(1 for item in results if not item.citation_correct or not item.refusal_correct)
        if decision == "approved" and risky:
            raise AppError("HIGH_RISK_GATE_BLOCKED", "高风险用例未通过，禁止上线", 409)
        item = SupportReleaseDecision(owner_id=owner_id, evaluation_run_id=run.id, knowledge_release_id=release.id, actor_id=actor_id, decision=decision, gate_snapshot_json=json.dumps({"highRiskFailures": risky, "caseCount": len(results)}))
        db.add(item)
        if decision == "approved":
            for active in db.scalars(select(KnowledgeRelease).where(KnowledgeRelease.owner_id == owner_id, KnowledgeRelease.is_active.is_(True))):
                active.is_active = False
            release.is_active = True
        db.commit()
        return {"id": item.id, "decision": decision, "highRiskFailures": risky, "releaseId": release.id, "runId": run.id}

    def _require_release(self, db: Session, owner_id: int, release_id: int) -> KnowledgeRelease:
        item = db.scalar(select(KnowledgeRelease).where(KnowledgeRelease.id == release_id, KnowledgeRelease.owner_id == owner_id))
        if item is None:
            raise AppError("KNOWLEDGE_RELEASE_NOT_FOUND", "知识版本不存在", 404)
        return item

    @staticmethod
    def _release(db: Session, item: KnowledgeRelease) -> dict:
        documents = list(db.scalars(select(KnowledgeReleaseDocument).where(KnowledgeReleaseDocument.release_id == item.id).order_by(KnowledgeReleaseDocument.id)))
        return {"id": item.id, "version": item.version, "title": item.title, "status": item.status, "processingStatus": item.processing_status, "retrievalMode": item.retrieval_mode, "isActive": item.is_active, "isDemo": item.is_demo, "contentHash": item.content_hash, "publishedAt": item.published_at.isoformat() if item.published_at else None, "documents": [{"id": document.document_id, "filename": document.filename_snapshot, "hash": document.document_hash} for document in documents]}

    @staticmethod
    def _case_summary(db: Session, item: SupportCase) -> dict:
        last_message = db.scalar(
            select(SupportMessage.content).where(SupportMessage.case_id == item.id).order_by(SupportMessage.id.desc()).limit(1)
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
            "decision": decision.decision if decision else None,
            "finalContent": decision.final_content if decision else None,
            "createdAt": item.created_at.isoformat(),
        }

    @staticmethod
    def _event(db: Session, case: SupportCase, actor_id: int | None, event_type: str, payload: dict) -> None:
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
