"""Deterministic demo seeding with fail-closed ownership and cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, inspect, or_, select, update
from sqlalchemy.orm import Session

from app.modules.conversations.models import (
    ChatRequestRun,
    Conversation,
    ConversationTurn,
    Message,
)
from app.modules.demo.catalog import DemoCatalog, load_demo_catalog
from app.modules.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
)
from app.modules.evaluation.repository import EvaluationCaseInput, EvaluationRepository
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
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
from app.modules.users.models import Organization, OrganizationMember, User
from app.modules.commerce.service import RetailService
from app.modules.commerce.models import (
    Basket,
    BasketItem,
    CommerceImport,
    MerchantProfile,
    Product,
)
from app.modules.orders.models import (
    CustomerSnapshot,
    Fulfillment,
    Order,
    OrderItem,
    OutboundMessage,
    Refund,
)
from app.modules.provenance.models import DataSource


class DemoSeedError(RuntimeError):
    """Base error for a demo operation that could not complete safely."""


class DemoOwnershipError(DemoSeedError):
    """Raised before mutation when a demo/non-demo ownership edge is unsafe."""


class DemoCleanupError(DemoSeedError):
    """Raised after rolling back DB deletion when external cleanup is incomplete."""

    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        super().__init__("demo cleanup failed: " + "; ".join(self.errors))


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    created_users: int = 0
    reused_users: int = 0
    created_knowledge_bases: int = 0
    reused_knowledge_bases: int = 0
    created_documents: int = 0
    reused_documents: int = 0
    created_evaluation_datasets: int = 0
    reused_evaluation_datasets: int = 0
    created_evaluation_cases: int = 0
    reused_evaluation_cases: int = 0
    created_conversations: int = 0
    reused_conversations: int = 0
    created_turns: int = 0
    reused_turns: int = 0
    created_messages: int = 0
    reused_messages: int = 0
    created_support_cases: int = 0
    reused_support_cases: int = 0


@dataclass(frozen=True, slots=True)
class DemoClearResult:
    removed_users: int = 0
    removed_knowledge_bases: int = 0
    removed_documents: int = 0
    removed_chunks: int = 0
    removed_evaluation_datasets: int = 0
    removed_evaluation_cases: int = 0
    removed_conversations: int = 0
    removed_turns: int = 0
    removed_messages: int = 0
    removed_request_runs: int = 0
    removed_trace_runs: int = 0
    removed_trace_nodes: int = 0
    removed_files: int = 0
    removed_vectors: int = 0
    removed_support_records: int = 0
    removed_order_records: int = 0
    removed_members: int = 0
    removed_organizations: int = 0
    external_cleanup_errors: tuple[str, ...] = ()

    @property
    def removed_records(self) -> int:
        return sum(
            (
                self.removed_users,
                self.removed_knowledge_bases,
                self.removed_documents,
                self.removed_chunks,
                self.removed_evaluation_datasets,
                self.removed_evaluation_cases,
                self.removed_conversations,
                self.removed_turns,
                self.removed_messages,
                self.removed_request_runs,
                self.removed_trace_runs,
                self.removed_trace_nodes,
                self.removed_support_records,
                self.removed_order_records,
            )
        )


@dataclass(frozen=True, slots=True)
class _OwnershipPlan:
    user_ids: tuple[int, ...] = ()
    base_ids: tuple[int, ...] = ()
    documents: tuple[KnowledgeDocument, ...] = ()
    chunk_ids: tuple[int, ...] = ()
    dataset_ids: tuple[int, ...] = ()
    case_ids: tuple[int, ...] = ()
    conversation_ids: tuple[str, ...] = ()
    turn_ids: tuple[int, ...] = ()
    message_ids: tuple[int, ...] = ()
    request_run_ids: tuple[int, ...] = ()
    trace_run_ids: tuple[str, ...] = ()
    trace_node_ids: tuple[int, ...] = ()
    ordinary_storage_paths: tuple[Path, ...] = ()

    @property
    def document_ids(self) -> tuple[int, ...]:
        return tuple(item.id for item in self.documents)

    @property
    def vector_document_ids(self) -> tuple[int, ...]:
        return tuple(item.id for item in self.documents if item.vector_indexed)


class DemoSeedService:
    """Create and clear one catalog while preserving every non-demo owner."""

    _conversation_title = "七日无理由退货咨询示例"
    _question = "订单签收后，七天无理由退货期限从哪天开始计算？"
    _answer = (
        "七日期间从消费者签收商品的次日开始计算，并应在期限内向商家发出退货通知。"
    )

    def __init__(
        self,
        container,
        *,
        catalog: DemoCatalog | None = None,
        evaluation_repository: EvaluationRepository | None = None,
    ):
        self.container = container
        self.catalog = catalog or load_demo_catalog(
            Path(__file__).resolve().parents[3] / "resources" / "demo"
        )
        self.evaluations = evaluation_repository or EvaluationRepository()

    def seed(
        self, db: Session, *, password: str, reset: bool = False
    ) -> DemoSeedResult:
        if len(password) < 10:
            raise ValueError("demo password must contain at least 10 characters")

        existing_user = self.container.user_repository.get_by_username(
            db, self.catalog.account.username
        )
        if existing_user is not None and not existing_user.is_demo:
            db.rollback()
            raise DemoOwnershipError(
                "ownership violation: demo username belongs to a non-demo user"
            )
        try:
            plan = self._ownership_plan(db)
            if existing_user is not None:
                self._validate_seed_identity(db, existing_user, plan)
                self._require_vector_cleanup_capability(plan)
                self._reject_shared_seed_files(plan)
            self._preflight_catalog_destinations(plan)
        except OSError as exc:
            db.rollback()
            raise DemoCleanupError(
                [f"file identity check failed during seed preflight: {exc}"]
            ) from exc
        except DemoSeedError:
            db.rollback()
            raise
        else:
            db.rollback()

        if reset:
            self.clear(db)

        counts = {field: 0 for field in DemoSeedResult.__dataclass_fields__}
        mutated = False
        try:
            user, created = self._upsert_user(db, password)
            mutated = True
            counts["created_users" if created else "reused_users"] += 1
            self._upsert_organization(db, user, password)

            bases_by_key: dict[str, KnowledgeBase] = {}
            for catalog_base in self.catalog.knowledge_bases:
                item, created = self._upsert_knowledge_base(
                    db,
                    user,
                    catalog_base.key,
                    catalog_base.name,
                    catalog_base.description,
                )
                bases_by_key[catalog_base.key] = item
                counts[
                    "created_knowledge_bases"
                    if created
                    else "reused_knowledge_bases"
                ] += 1

            documents_by_key: dict[str, KnowledgeDocument] = {}
            for source in self.catalog.documents:
                catalog_base = next(
                    item
                    for item in self.catalog.knowledge_bases
                    if source.key in item.document_keys
                )
                document, created = self._upsert_document(
                    db, user, bases_by_key[catalog_base.key], source
                )
                documents_by_key[source.key] = document
                counts[
                    "created_documents" if created else "reused_documents"
                ] += 1

            for document in documents_by_key.values():
                self._reconcile_ingestion(db, document)

            _, dataset_created, created_cases, reused_cases = (
                self._upsert_evaluation_dataset(db, user, bases_by_key)
            )
            counts[
                "created_evaluation_datasets"
                if dataset_created
                else "reused_evaluation_datasets"
            ] += 1
            counts["created_evaluation_cases"] += created_cases
            counts["reused_evaluation_cases"] += reused_cases

            for key, value in self._upsert_history(
                db, user, bases_by_key, documents_by_key
            ).items():
                counts[key] += value
            created_support, reused_support = self._upsert_support_workflow(
                db, user, documents_by_key
            )
            counts["created_support_cases"] += created_support
            counts["reused_support_cases"] += reused_support
            return DemoSeedResult(**counts)
        except DemoOwnershipError:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            if mutated:
                try:
                    self.clear(db)
                except DemoCleanupError as cleanup_exc:
                    raise DemoCleanupError(
                        [f"seed failure: {exc}", *cleanup_exc.errors]
                    ) from exc
            if isinstance(exc, DemoSeedError):
                raise
            raise DemoSeedError(str(exc)) from exc

    def clear(self, db: Session) -> DemoClearResult:
        """Plan ownership, delete in DB, clean externals, then commit once."""

        try:
            plan = self._ownership_plan(db)
            self._require_vector_cleanup_capability(plan)
            file_deletions = self._plan_file_cleanup(plan)
        except OSError as exc:
            db.rollback()
            raise DemoCleanupError(
                [f"file identity check failed: {exc}"]
            ) from exc
        except DemoSeedError:
            db.rollback()
            raise
        if not plan.user_ids:
            db.rollback()
            return DemoClearResult()

        try:
            counts = self._delete_planned_rows(db, plan)
            removed_vectors, removed_files, cleanup_errors = self._cleanup_externals(
                plan, file_deletions
            )
            if cleanup_errors:
                db.rollback()
                raise DemoCleanupError(cleanup_errors)
            db.commit()
        except DemoCleanupError:
            raise
        except Exception:
            db.rollback()
            raise

        try:
            self._storage_root().rmdir()
        except OSError:
            pass
        return DemoClearResult(
            **counts,
            removed_files=removed_files,
            removed_vectors=removed_vectors,
        )

    def _ownership_plan(self, db: Session) -> _OwnershipPlan:
        cross_owner_dataset = db.scalar(
            select(EvaluationDataset.id)
            .join(User, EvaluationDataset.owner_id == User.id)
            .where(
                EvaluationDataset.is_demo.is_(True),
                User.is_demo.is_(False),
            )
            .limit(1)
        )
        if cross_owner_dataset is not None:
            raise DemoOwnershipError(
                "ownership violation: demo dataset belongs to ordinary user"
            )
        demo_user_ids = tuple(
            db.scalars(select(User.id).where(User.is_demo.is_(True)))
        )
        if not demo_user_ids:
            return _OwnershipPlan(
                ordinary_storage_paths=tuple(
                    Path(value)
                    for value in db.scalars(
                        select(KnowledgeDocument.storage_path)
                    )
                )
            )
        demo_users = set(demo_user_ids)

        self._validate_order_ownership(db, demo_users)

        base_ids = tuple(
            db.scalars(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.owner_id.in_(demo_user_ids)
                )
            )
        )
        demo_bases = set(base_ids)
        candidate_documents = list(
            db.scalars(
                select(KnowledgeDocument).where(
                    or_(
                        KnowledgeDocument.uploader_id.in_(demo_user_ids),
                        KnowledgeDocument.knowledge_base_id.in_(base_ids),
                    )
                )
            )
        )
        for item in candidate_documents:
            if not (
                item.uploader_id in demo_users
                and item.knowledge_base_id in demo_bases
            ):
                raise DemoOwnershipError(
                    "ownership violation: knowledge document crosses demo boundary"
                )
            self._require_managed_path(Path(item.storage_path))
        document_ids = tuple(item.id for item in candidate_documents)
        demo_documents = set(document_ids)

        candidate_chunks = list(
            db.scalars(
                select(KnowledgeChunk).where(
                    or_(
                        KnowledgeChunk.document_id.in_(document_ids),
                        KnowledgeChunk.knowledge_base_id.in_(base_ids),
                    )
                )
            )
        ) if document_ids or base_ids else []
        documents_by_id = {item.id: item for item in candidate_documents}
        for chunk in candidate_chunks:
            document = documents_by_id.get(chunk.document_id)
            if (
                document is None
                or chunk.knowledge_base_id not in demo_bases
                or chunk.knowledge_base_id != document.knowledge_base_id
            ):
                raise DemoOwnershipError(
                    "ownership violation: knowledge chunk crosses demo boundary"
                )

        candidate_datasets = list(
            db.scalars(
                select(EvaluationDataset).where(
                    or_(
                        EvaluationDataset.owner_id.in_(demo_user_ids),
                        EvaluationDataset.is_demo.is_(True),
                    )
                )
            )
        )
        for dataset in candidate_datasets:
            if dataset.is_demo and dataset.owner_id not in demo_users:
                raise DemoOwnershipError(
                    "ownership violation: demo dataset belongs to ordinary user"
                )
        dataset_ids = tuple(
            item.id
            for item in candidate_datasets
            if item.owner_id in demo_users
        )
        case_ids = tuple(
            db.scalars(
                select(EvaluationCase.id).where(
                    EvaluationCase.dataset_id.in_(dataset_ids)
                )
            )
        ) if dataset_ids else ()

        conversation_ids = tuple(
            db.scalars(
                select(Conversation.id).where(
                    Conversation.user_id.in_(demo_user_ids)
                )
            )
        )
        demo_conversations = set(conversation_ids)
        turns = list(
            db.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id.in_(conversation_ids)
                )
            )
        ) if conversation_ids else []
        turn_ids = tuple(item.id for item in turns)
        demo_turns = set(turn_ids)

        messages = list(
            db.scalars(
                select(Message).where(
                    or_(
                        Message.user_id.in_(demo_user_ids),
                        Message.conversation_id.in_(conversation_ids),
                    )
                )
            )
        )
        for message in messages:
            if not (
                message.user_id in demo_users
                and message.conversation_id in demo_conversations
                and (message.turn_id is None or message.turn_id in demo_turns)
            ):
                raise DemoOwnershipError(
                    "ownership violation: message crosses demo boundary"
                )
        messages_by_id = {item.id: item for item in messages}
        message_ids = tuple(messages_by_id)
        self._validate_turn_message_identity(
            turns, messages_by_id, demo_user_ids
        )

        request_runs = list(db.scalars(select(ChatRequestRun)))
        planned_requests: list[int] = []
        for run in request_runs:
            touches_demo = (
                run.user_id in demo_users
                or run.conversation_id in demo_conversations
                or run.turn_id in demo_turns
                or run.user_message_id in messages_by_id
                or run.assistant_message_id in messages_by_id
            )
            if not touches_demo:
                continue
            if not (
                run.user_id in demo_users
                and (
                    run.conversation_id is None
                    or run.conversation_id in demo_conversations
                )
                and (run.turn_id is None or run.turn_id in demo_turns)
                and (
                    run.user_message_id is None
                    or run.user_message_id in messages_by_id
                )
                and (
                    run.assistant_message_id is None
                    or run.assistant_message_id in messages_by_id
                )
            ):
                raise DemoOwnershipError(
                    "ownership violation: request run crosses demo boundary"
                )
            planned_requests.append(run.id)

        trace_runs = list(db.scalars(select(RagTraceRun)))
        planned_traces: list[str] = []
        for run in trace_runs:
            touches_demo = (
                run.user_id in demo_users
                or run.conversation_id in demo_conversations
                or run.turn_id in demo_turns
            )
            if not touches_demo:
                continue
            if not (
                run.user_id in demo_users
                and (
                    run.conversation_id is None
                    or run.conversation_id in demo_conversations
                )
                and (run.turn_id is None or run.turn_id in demo_turns)
            ):
                raise DemoOwnershipError(
                    "ownership violation: trace run crosses demo boundary"
                )
            planned_traces.append(run.id)
        trace_node_ids = tuple(
            db.scalars(
                select(RagTraceNode.id).where(
                    RagTraceNode.run_id.in_(planned_traces)
                )
            )
        ) if planned_traces else ()

        ordinary_paths = tuple(
            Path(value)
            for value in db.scalars(
                select(KnowledgeDocument.storage_path).where(
                    KnowledgeDocument.id.not_in(document_ids)
                )
            )
        )
        return _OwnershipPlan(
            user_ids=demo_user_ids,
            base_ids=base_ids,
            documents=tuple(candidate_documents),
            chunk_ids=tuple(item.id for item in candidate_chunks),
            dataset_ids=dataset_ids,
            case_ids=case_ids,
            conversation_ids=conversation_ids,
            turn_ids=turn_ids,
            message_ids=message_ids,
            request_run_ids=tuple(planned_requests),
            trace_run_ids=tuple(planned_traces),
            trace_node_ids=trace_node_ids,
            ordinary_storage_paths=ordinary_paths,
        )

    @staticmethod
    def _validate_turn_message_identity(
        turns: list[ConversationTurn],
        messages_by_id: dict[int, Message],
        demo_user_ids: tuple[int, ...],
    ) -> None:
        demo_users = set(demo_user_ids)
        for turn in turns:
            pairs = (
                (turn.user_message_id, "user"),
                (turn.active_assistant_message_id, "assistant"),
            )
            for message_id, expected_role in pairs:
                if message_id is None:
                    continue
                message = messages_by_id.get(message_id)
                if (
                    message is None
                    or message.user_id not in demo_users
                    or message.conversation_id != turn.conversation_id
                    or message.turn_id != turn.id
                    or message.role != expected_role
                ):
                    raise DemoOwnershipError(
                        "ownership identity violation: turn points to mismatched message"
                    )

    def _validate_seed_identity(
        self, db: Session, user: User, plan: _OwnershipPlan
    ) -> None:
        if user.id not in plan.user_ids:
            raise DemoOwnershipError(
                "ownership identity violation: reused demo user is outside closure"
            )
        bases = list(
            db.scalars(
                select(KnowledgeBase).where(KnowledgeBase.id.in_(plan.base_ids))
            )
        ) if plan.base_ids else []
        bases_by_key: dict[str, KnowledgeBase | None] = {}
        for catalog_base in self.catalog.knowledge_bases:
            stable_name = f"{catalog_base.name} [demo:{catalog_base.key}]"
            matches = [
                item
                for item in bases
                if item.owner_id == user.id and item.name == stable_name
            ]
            if len(matches) > 1:
                raise DemoOwnershipError(
                    "ownership identity violation: ambiguous catalog knowledge base"
                )
            bases_by_key[catalog_base.key] = matches[0] if matches else None

        user_documents = [
            item for item in plan.documents if item.uploader_id == user.id
        ]
        for source in self.catalog.documents:
            source_path = self.catalog.root / source.local_path
            filename = f"{source.key}{source_path.suffix.lower() or '.txt'}"
            matches = [
                item for item in user_documents if item.filename == filename
            ]
            if len(matches) > 1:
                raise DemoOwnershipError(
                    "ownership identity violation: ambiguous catalog document"
                )
            if not matches:
                continue
            document = matches[0]
            catalog_base = next(
                item
                for item in self.catalog.knowledge_bases
                if source.key in item.document_keys
            )
            expected_base = bases_by_key[catalog_base.key]
            allowed_paths = {
                self._lexical_key(self._storage_root() / filename),
                self._lexical_key(self._legacy_storage_root() / filename),
            }
            if (
                expected_base is None
                or document.knowledge_base_id != expected_base.id
                or document.uploader_id != user.id
                or self._lexical_key(Path(document.storage_path))
                not in allowed_paths
            ):
                raise DemoOwnershipError(
                    "ownership identity violation: catalog document mismatch"
                )

        catalog_dataset = self.catalog.evaluation_dataset
        dataset_name = (
            f"{catalog_dataset.name} [demo:{catalog_dataset.key}]"
        )
        datasets = list(
            db.scalars(
                select(EvaluationDataset).where(
                    EvaluationDataset.name == dataset_name
                )
            )
        )
        reused_datasets = [item for item in datasets if item.owner_id == user.id]
        if len(reused_datasets) > 1 or (
            reused_datasets and not reused_datasets[0].is_demo
        ):
            raise DemoOwnershipError(
                "ownership identity violation: catalog dataset mismatch"
            )
        conversations = list(
            db.scalars(
                select(Conversation).where(
                    Conversation.user_id == user.id,
                    Conversation.title == self._conversation_title,
                )
            )
        )
        if len(conversations) > 1:
            raise DemoOwnershipError(
                "ownership identity violation: ambiguous demo conversation"
            )

    def _delete_planned_rows(
        self, db: Session, plan: _OwnershipPlan
    ) -> dict[str, int]:
        support_removed = self._delete_support_rows(db, plan.user_ids)
        order_removed = self._delete_order_rows(db, plan.user_ids)
        for owner_id in plan.user_ids:
            RetailService().clear_managed_snapshots(db, owner_id, commit=False)
        # 商家画像（merchant_profiles.owner_id → users_v2）不在快照清理范围内，
        # FK 强制后必须显式删除，否则 users 删除被拒
        if plan.user_ids:
            self._delete_ids(
                db,
                MerchantProfile,
                MerchantProfile.id,
                tuple(
                    db.scalars(
                        select(MerchantProfile.id).where(
                            MerchantProfile.owner_id.in_(plan.user_ids)
                        )
                    )
                ),
            )
        # FK 强制后按依赖顺序补删：经营复测 → 优化任务 → 评测运行 →
        # 知识发布（决策/版本，成员级联）——必须在 datasets/cases/documents 删除前
        if plan.user_ids:
            from app.modules.optimization.models import (
                OptimizationTask,
                OptimizationVerificationRun,
            )

            for model in (OptimizationVerificationRun, OptimizationTask):
                ids = tuple(
                    db.scalars(
                        select(model.id).where(model.owner_id.in_(plan.user_ids))
                    )
                )
                self._delete_ids(db, model, model.id, ids)
            self._delete_ids(
                db,
                SupportReleaseDecision,
                SupportReleaseDecision.id,
                tuple(
                    db.scalars(
                        select(SupportReleaseDecision.id).where(
                            SupportReleaseDecision.owner_id.in_(plan.user_ids)
                        )
                    )
                ),
            )
            release_ids = tuple(
                db.scalars(
                    select(KnowledgeRelease.id).where(
                        KnowledgeRelease.owner_id.in_(plan.user_ids)
                    )
                )
            )
            self._delete_ids(db, KnowledgeRelease, KnowledgeRelease.id, release_ids)
            self._delete_ids(
                db,
                EvaluationRun,
                EvaluationRun.id,
                tuple(
                    db.scalars(
                        select(EvaluationRun.id).where(
                            EvaluationRun.owner_id.in_(plan.user_ids)
                        )
                    )
                ),
            )
        counts = {
            "removed_request_runs": self._delete_ids(
                db, ChatRequestRun, ChatRequestRun.id, plan.request_run_ids
            ),
            "removed_trace_nodes": self._delete_ids(
                db, RagTraceNode, RagTraceNode.id, plan.trace_node_ids
            ),
            "removed_trace_runs": self._delete_ids(
                db, RagTraceRun, RagTraceRun.id, plan.trace_run_ids
            ),
            "removed_support_records": support_removed,
            "removed_order_records": order_removed,
        }
        if plan.turn_ids:
            db.execute(
                update(ConversationTurn)
                .where(ConversationTurn.id.in_(plan.turn_ids))
                .values(user_message_id=None, active_assistant_message_id=None)
            )
            db.execute(
                update(Message)
                .where(Message.turn_id.in_(plan.turn_ids))
                .values(turn_id=None)
            )
        counts.update(
            removed_messages=self._delete_ids(
                db, Message, Message.id, plan.message_ids
            ),
            removed_turns=self._delete_ids(
                db, ConversationTurn, ConversationTurn.id, plan.turn_ids
            ),
            removed_conversations=self._delete_ids(
                db, Conversation, Conversation.id, plan.conversation_ids
            ),
            removed_evaluation_cases=self._delete_ids(
                db, EvaluationCase, EvaluationCase.id, plan.case_ids
            ),
            removed_evaluation_datasets=self._delete_ids(
                db, EvaluationDataset, EvaluationDataset.id, plan.dataset_ids
            ),
            removed_chunks=self._delete_ids(
                db, KnowledgeChunk, KnowledgeChunk.id, plan.chunk_ids
            ),
            removed_documents=self._delete_ids(
                db, KnowledgeDocument, KnowledgeDocument.id, plan.document_ids
            ),
            removed_knowledge_bases=self._delete_ids(
                db, KnowledgeBase, KnowledgeBase.id, plan.base_ids
            ),
        )
        if plan.user_ids:
            org_ids = tuple(
                db.scalars(
                    select(Organization.id).where(
                        Organization.owner_user_id.in_(plan.user_ids)
                    )
                )
            )
            if org_ids:
                member_ids = tuple(
                    db.scalars(
                        select(OrganizationMember.id).where(
                            OrganizationMember.org_id.in_(org_ids)
                        )
                    )
                )
                counts["removed_members"] = self._delete_ids(
                    db, OrganizationMember, OrganizationMember.id, member_ids
                )
                counts["removed_organizations"] = self._delete_ids(
                    db, Organization, Organization.id, org_ids
                )
        counts["removed_users"] = self._delete_ids(
            db, User, User.id, plan.user_ids
        )
        db.flush()
        return counts

    @staticmethod
    def _delete_support_rows(db: Session, user_ids: tuple[int, ...]) -> int:
        if not user_ids:
            return 0
        bind = db.get_bind()
        if not inspect(bind).has_table("support_cases"):
            return 0
        case_ids = tuple(
            db.scalars(select(SupportCase.id).where(SupportCase.owner_id.in_(user_ids)))
        )
        release_ids = tuple(
            db.scalars(
                select(KnowledgeRelease.id).where(KnowledgeRelease.owner_id.in_(user_ids))
            )
        )
        deletions = (
            (OutboundMessage, OutboundMessage.owner_id.in_(user_ids)),
            (SupportReleaseDecision, SupportReleaseDecision.owner_id.in_(user_ids)),
            (SupportQualityLabel, SupportQualityLabel.owner_id.in_(user_ids)),
            (ReplyDecision, ReplyDecision.case_id.in_(case_ids)),
            (SupportEscalation, SupportEscalation.owner_id.in_(user_ids)),
            (SupportMessage, SupportMessage.case_id.in_(case_ids)),
            (SupportEvent, SupportEvent.case_id.in_(case_ids)),
            (ReplySuggestion, ReplySuggestion.case_id.in_(case_ids)),
            (KnowledgeGap, KnowledgeGap.owner_id.in_(user_ids)),
            (KnowledgeReleaseDocument, KnowledgeReleaseDocument.release_id.in_(release_ids)),
            (KnowledgeRelease, KnowledgeRelease.owner_id.in_(user_ids)),
            (SupportCase, SupportCase.owner_id.in_(user_ids)),
        )
        removed = 0
        for model, predicate in deletions:
            result = db.execute(delete(model).where(predicate))
            removed += int(result.rowcount or 0)
        return removed

    @staticmethod
    def _delete_order_rows(db: Session, user_ids: tuple[int, ...]) -> int:
        if not user_ids or not inspect(db.get_bind()).has_table("orders"):
            return 0
        order_ids = tuple(
            db.scalars(select(Order.id).where(Order.owner_id.in_(user_ids)))
        )
        deletions = (
            (Refund, Refund.order_id.in_(order_ids)),
            (Fulfillment, Fulfillment.order_id.in_(order_ids)),
            (OrderItem, OrderItem.order_id.in_(order_ids)),
            (Order, Order.id.in_(order_ids)),
            (CustomerSnapshot, CustomerSnapshot.owner_id.in_(user_ids)),
        )
        removed = 0
        for model, predicate in deletions:
            result = db.execute(delete(model).where(predicate))
            removed += int(result.rowcount or 0)
        return removed

    @staticmethod
    def _validate_order_ownership(db: Session, demo_users: set[int]) -> None:
        if not demo_users or not inspect(db.get_bind()).has_table("orders"):
            return
        mismatched_case = db.scalar(
            select(SupportCase.id)
            .join(Order, Order.id == SupportCase.order_id)
            .where(
                or_(
                    SupportCase.owner_id.in_(demo_users),
                    Order.owner_id.in_(demo_users),
                ),
                SupportCase.owner_id != Order.owner_id,
            )
            .limit(1)
        )
        mismatched_customer = db.scalar(
            select(Order.id)
            .join(CustomerSnapshot, CustomerSnapshot.id == Order.customer_snapshot_id)
            .where(
                or_(
                    Order.owner_id.in_(demo_users),
                    CustomerSnapshot.owner_id.in_(demo_users),
                ),
                Order.owner_id != CustomerSnapshot.owner_id,
            )
            .limit(1)
        )
        mismatched_product = db.scalar(
            select(OrderItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .where(
                or_(Order.owner_id.in_(demo_users), Product.owner_id.in_(demo_users)),
                Order.owner_id != Product.owner_id,
            )
            .limit(1)
        )
        mismatched_outbound = db.scalar(
            select(OutboundMessage.id)
            .join(SupportCase, SupportCase.id == OutboundMessage.case_id)
            .where(
                or_(
                    OutboundMessage.owner_id.in_(demo_users),
                    SupportCase.owner_id.in_(demo_users),
                ),
                OutboundMessage.owner_id != SupportCase.owner_id,
            )
            .limit(1)
        )
        if any(
            item is not None
            for item in (
                mismatched_case,
                mismatched_customer,
                mismatched_product,
                mismatched_outbound,
            )
        ):
            raise DemoOwnershipError(
                "ownership violation: order context crosses demo boundary"
            )

    def _cleanup_externals(
        self, plan: _OwnershipPlan, file_deletions: tuple[Path, ...]
    ) -> tuple[int, int, list[str]]:
        errors: list[str] = []
        removed_vectors = 0
        indexer = self.container.knowledge.vector_indexer
        if indexer is not None:
            for document_id in plan.vector_document_ids:
                try:
                    asyncio.run(indexer.store.delete_document(document_id))
                    removed_vectors += 1
                except Exception as exc:  # aggregate every retryable failure
                    errors.append(f"vector cleanup {document_id}: {exc}")

        removed_files = 0
        for path in file_deletions:
            try:
                path.unlink(missing_ok=True)
                removed_files += 1
            except OSError as exc:
                errors.append(f"file cleanup {path}: {exc}")
        return removed_vectors, removed_files, errors

    def _plan_file_cleanup(self, plan: _OwnershipPlan) -> tuple[Path, ...]:
        deletions: list[Path] = []
        for document in plan.documents:
            path = Path(document.storage_path)
            target_stat = self._require_managed_file_target(path)
            if target_stat is None:
                continue
            if self._shares_regular_file(path, plan.ordinary_storage_paths):
                continue
            deletions.append(path)
        return tuple(deletions)

    def _require_vector_cleanup_capability(self, plan: _OwnershipPlan) -> None:
        if (
            plan.vector_document_ids
            and self.container.knowledge.vector_indexer is None
        ):
            raise DemoCleanupError(
                ["vector cleanup capability is unavailable for indexed demo documents"]
            )

    def _reject_shared_seed_files(self, plan: _OwnershipPlan) -> None:
        try:
            for document in plan.documents:
                path = Path(document.storage_path)
                self._require_managed_file_target(path)
                if self._shares_regular_file(path, plan.ordinary_storage_paths):
                    raise DemoOwnershipError(
                        "ownership violation: managed demo file is shared by ordinary data"
                    )
        except OSError as exc:
            raise DemoCleanupError(
                [f"file identity check failed during seed preflight: {exc}"]
            ) from exc

    def _preflight_catalog_destinations(self, plan: _OwnershipPlan) -> None:
        try:
            for source in self.catalog.documents:
                source_path = self.catalog.root / source.local_path
                suffix = source_path.suffix.lower() or ".txt"
                destination = self._storage_root() / f"{source.key}{suffix}"
                self._require_managed_file_target(destination)
                if self._shares_regular_file(
                    destination, plan.ordinary_storage_paths
                ):
                    raise DemoOwnershipError(
                        "ownership violation: prospective demo file is shared by ordinary data"
                    )
        except OSError as exc:
            raise DemoCleanupError(
                [f"file identity check failed during seed preflight: {exc}"]
            ) from exc

    def _upsert_user(self, db: Session, password: str) -> tuple[User, bool]:
        user = self.container.user_repository.get_by_username(
            db, self.catalog.account.username
        )
        if user is not None:
            if not user.is_demo:
                raise DemoOwnershipError(
                    "ownership violation: refusing to adopt non-demo user"
                )
            if not self.container.auth.passwords.verify(password, user.password_hash):
                user.password_hash = self.container.auth.passwords.hash(password)
                db.commit()
            return user, False
        user = self.container.user_repository.create(
            db,
            username=self.catalog.account.username,
            password_hash=self.container.auth.passwords.hash(password),
        )
        user.is_demo = True
        db.commit()
        return user, True

    def _upsert_organization(
        self, db: Session, owner_user: User, password: str
    ) -> None:
        """创建演示商家组织，并准备各角色演示账号与明确成员关系。

        账号密码与演示商家账号一致；成员关系替代旧的"管理员自动代理"魔法：
        support-admin / demo-supervisor 等只有作为组织成员时才可访问商家数据。
        support-admin 是非 demo 的平台管理员账号（与 cli create-admin 一致），
        seed 仅负责把它绑定进演示组织；demo-* 账号随 seed 创建、clear 清理。
        """
        org = db.scalar(
            select(Organization).where(
                Organization.owner_user_id == owner_user.id
            )
        )
        if org is None:
            org = Organization(
                name="邻里鲜选演示商家",
                owner_user_id=owner_user.id,
                is_demo=True,
            )
            db.add(org)
            db.flush()
        accounts = {
            "support-admin": ("admin", "admin", False),
            "demo-supervisor": ("supervisor", "supervisor", True),
            "demo-operator": ("operator", "operator", True),
            "demo-agent": ("user", "user", True),
        }
        # 商家 owner 本人也以成员身份绑定组织（角色 admin）
        accounts = {"merchant-demo": ("admin", "admin", True), **accounts}
        for username, (member_role, global_role, demo) in accounts.items():
            account = self.container.user_repository.get_by_username(db, username)
            if account is None:
                account = self.container.user_repository.create(
                    db,
                    username=username,
                    password_hash=self.container.auth.passwords.hash(password),
                )
                account.is_demo = demo
                account.role = global_role
                db.flush()
            elif demo and not account.is_demo:
                raise DemoOwnershipError(
                    f"ownership violation: {username} belongs to a non-demo user"
                )
            if demo and account.role != global_role:
                account.role = global_role
            member = db.scalar(
                select(OrganizationMember).where(
                    OrganizationMember.org_id == org.id,
                    OrganizationMember.user_id == account.id,
                )
            )
            if member is None:
                db.add(
                    OrganizationMember(
                        org_id=org.id, user_id=account.id, role=member_role
                    )
                )
        db.commit()

    def _upsert_knowledge_base(
        self,
        db: Session,
        user: User,
        stable_key: str,
        name: str,
        description: str | None,
    ) -> tuple[KnowledgeBase, bool]:
        stable_name = f"{name} [demo:{stable_key}]"
        item = db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.owner_id == user.id,
                KnowledgeBase.name == stable_name,
            )
        )
        if item is not None:
            item.description = description
            db.commit()
            return item, False
        # 演示账号即组织 owner（_upsert_organization 设置 owner_user_id=user.id），
        # 因此 owner_id（商家数据 owner）与 user.id 一致。
        return (
            self.container.knowledge.create_base(
                db, owner_id=user.id, name=stable_name, description=description
            ),
            True,
        )

    def _upsert_document(
        self, db: Session, user: User, base: KnowledgeBase, source
    ) -> tuple[KnowledgeDocument, bool]:
        source_path = self.catalog.root / source.local_path
        suffix = source_path.suffix.lower() or ".txt"
        filename = f"{source.key}{suffix}"
        destination = self._storage_root() / filename
        self._require_managed_file_target(destination)
        item = db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == base.id,
                KnowledgeDocument.uploader_id == user.id,
                KnowledgeDocument.filename == filename,
            )
        )
        created = item is None
        previous_path: Path | None = None
        if item is not None:
            previous_path = Path(item.storage_path)
            allowed_paths = {
                self._lexical_key(destination),
                self._lexical_key(self._legacy_storage_root() / filename),
            }
            if self._lexical_key(previous_path) not in allowed_paths:
                raise DemoOwnershipError(
                    "ownership identity violation: demo document storage path changed"
                )

        ordinary_query = select(KnowledgeDocument.storage_path)
        if item is not None:
            ordinary_query = ordinary_query.where(KnowledgeDocument.id != item.id)
        ordinary_paths = tuple(
            Path(value) for value in db.scalars(ordinary_query)
        )
        if self._shares_regular_file(destination, ordinary_paths):
            raise DemoOwnershipError(
                "ownership violation: refusing to overwrite shared managed file"
            )
        if item is None:
            # 演示账号即组织 owner：owner_id（商家数据 owner）与 uploader 一致
            item = self.container.knowledge.create_document(
                db,
                base_id=base.id,
                uploader_id=user.id,
                owner_id=user.id,
                filename=filename,
                storage_path=str(destination),
                file_size=source_path.stat().st_size,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        target_stat = self._require_managed_file_target(destination)
        if target_stat is not None and self._is_link_or_reparse(target_stat):
            destination.unlink()
        shutil.copyfile(source_path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        item.storage_path = str(destination)
        item.file_size = destination.stat().st_size
        item.content_origin = source.content_origin
        item.source_url = source.source_url
        item.source_publisher = source.source_publisher
        item.source_retrieved_at = source.source_retrieved_at
        item.source_usage_note = source.source_usage_note
        item.source_title = source.title
        item.source_jurisdiction = "中国大陆" if source.content_origin == "public_summary" else "虚构演示商家"
        item.source_effective_at = None
        item.next_review_at = (
            source.source_retrieved_at + timedelta(days=365)
            if source.source_retrieved_at is not None else None
        )
        item.review_status = "current"
        item.applicability_json = json.dumps(
            ["中国大陆网络零售客服"] if source.content_origin == "public_summary" else ["本项目虚构商家演示"],
            ensure_ascii=False,
        )
        item.exclusions_json = json.dumps(
            ["不替代官方法律原文", "不构成法律意见"] if source.content_origin == "public_summary" else ["不代表真实商家承诺"],
            ensure_ascii=False,
        )
        item.license_or_usage_note = source.source_usage_note or "项目原创演示材料"
        item.demo_content_sha256 = digest
        db.commit()
        if (
            previous_path is not None
            and self._lexical_key(previous_path) != self._lexical_key(destination)
        ):
            self._require_managed_file_target(previous_path)
            previous_path.unlink(missing_ok=True)
        return item, created

    def _reconcile_ingestion(
        self, db: Session, document: KnowledgeDocument
    ) -> None:
        if self.container.knowledge.vector_indexer is not None:
            # Persist cleanup ownership before the vector store can receive even
            # one record. A partial upsert must remain discoverable on failure.
            document.vector_indexed = True
            db.commit()
        ingested = self.container.knowledge.ingest_document(db, document.id)
        if ingested.status != "indexed":
            raise DemoSeedError(
                ingested.error_message
                or f"failed to index demo document {ingested.filename}"
            )
        path = Path(ingested.storage_path)
        expected_chunks = self.container.knowledge.chunker.split(
            self.container.knowledge.parser.parse(path)
        )
        persisted_chunks = list(
            db.scalars(
                select(KnowledgeChunk.content)
                .where(KnowledgeChunk.document_id == ingested.id)
                .order_by(KnowledgeChunk.position)
            )
        )
        if persisted_chunks != expected_chunks:
            raise DemoSeedError(
                f"demo index generation mismatch for {ingested.filename}"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ingested.demo_content_sha256:
            raise DemoSeedError(
                f"managed demo content changed during indexing: {ingested.filename}"
            )
        ingested.demo_indexed_sha256 = digest
        ingested.vector_indexed = self.container.knowledge.vector_indexer is not None
        db.commit()

    def _upsert_evaluation_dataset(
        self,
        db: Session,
        user: User,
        bases_by_key: dict[str, KnowledgeBase],
    ) -> tuple[EvaluationDataset, bool, int, int]:
        catalog_dataset = self.catalog.evaluation_dataset
        stable_name = f"{catalog_dataset.name} [demo:{catalog_dataset.key}]"
        inputs = [
            self._case_input(case, bases_by_key)
            for case in self.catalog.evaluation_cases
        ]
        dataset = db.scalar(
            select(EvaluationDataset).where(
                EvaluationDataset.owner_id == user.id,
                EvaluationDataset.name == stable_name,
            )
        )
        if dataset is None:
            dataset = self.evaluations.create_dataset_with_cases(
                db,
                owner_id=user.id,
                name=stable_name,
                description=catalog_dataset.description,
                is_demo=True,
                cases=inputs,
            )
            return dataset, True, len(inputs), 0
        if not dataset.is_demo:
            raise DemoOwnershipError(
                "ownership violation: refusing to adopt non-demo evaluation dataset"
            )
        dataset.description = catalog_dataset.description
        existing = {
            case.case_key: case
            for case in db.scalars(
                select(EvaluationCase).where(
                    EvaluationCase.dataset_id == dataset.id
                )
            )
        }
        created = 0
        reused = 0
        catalog_keys: set[str] = set()
        for case_input in inputs:
            case_key = case_input.case_key
            catalog_keys.add(case_key)
            case = existing.get(case_key)
            if case is None:
                case = EvaluationCase(dataset_id=dataset.id, case_key=case_key)
                db.add(case)
                created += 1
            else:
                reused += 1
            self._apply_case(case, case_input)
        stale_ids = [
            case.id for key, case in existing.items() if key not in catalog_keys
        ]
        if stale_ids:
            db.execute(delete(EvaluationCase).where(EvaluationCase.id.in_(stale_ids)))
        db.commit()
        return dataset, False, created, reused

    def _case_input(
        self, case, bases_by_key: dict[str, KnowledgeBase]
    ) -> EvaluationCaseInput:
        referenced = set(case.expected_document_keys)
        base_ids = [
            bases_by_key[item.key].id
            for item in self.catalog.knowledge_bases
            if referenced.intersection(item.document_keys)
        ]
        return EvaluationCaseInput(
            case_key=case.key,
            question=case.question,
            category=case.category,
            difficulty=case.difficulty,
            knowledge_base_ids=base_ids,
            expected_points=list(case.expected_points),
            expected_document_keys=list(case.expected_document_keys),
            should_refuse=case.should_refuse,
            reference_answer=case.reference_answer,
        )

    @staticmethod
    def _apply_case(case: EvaluationCase, item: EvaluationCaseInput) -> None:
        case.question = item.question
        case.category = item.category
        case.difficulty = item.difficulty
        case.knowledge_base_ids_json = json.dumps(item.knowledge_base_ids)
        case.expected_points_json = json.dumps(item.expected_points, ensure_ascii=False)
        case.expected_document_keys_json = json.dumps(
            item.expected_document_keys, ensure_ascii=False
        )
        case.should_refuse = item.should_refuse
        case.reference_answer = item.reference_answer

    def _upsert_history(
        self,
        db: Session,
        user: User,
        bases_by_key: dict[str, KnowledgeBase],
        documents_by_key: dict[str, KnowledgeDocument],
    ) -> dict[str, int]:
        counts = {
            "created_conversations": 0,
            "reused_conversations": 0,
            "created_turns": 0,
            "reused_turns": 0,
            "created_messages": 0,
            "reused_messages": 0,
        }
        conversations = list(
            db.scalars(
                select(Conversation).where(
                    Conversation.user_id == user.id,
                    Conversation.title == self._conversation_title,
                )
            )
        )
        if len(conversations) > 1:
            raise DemoOwnershipError(
                "ownership identity violation: ambiguous demo conversation"
            )
        conversation = conversations[0] if conversations else None
        if conversation is None:
            conversation = self.container.conversations.create(
                db, user.id, self._conversation_title
            )
            counts["created_conversations"] = 1
        else:
            counts["reused_conversations"] = 1
        turn = db.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == conversation.id,
                ConversationTurn.sequence == 1,
            )
        )
        if turn is None:
            turn, user_message = self.container.conversations.create_turn(
                db,
                conversation_id=conversation.id,
                user_id=user.id,
                question=self._question,
                rag_enabled=True,
                deep_thinking=False,
                knowledge_base_ids=[item.id for item in bases_by_key.values()],
            )
            counts["created_turns"] = 1
            counts["created_messages"] = 1
        else:
            counts["reused_turns"] = 1
            user_message = (
                db.get(Message, turn.user_message_id)
                if turn.user_message_id is not None
                else None
            )
            self._require_history_message(
                user_message, turn, user, "user", allow_missing=True
            )
            if user_message is None:
                user_message = self.container.conversations.add_message(
                    db,
                    conversation_id=conversation.id,
                    user_id=user.id,
                    role="user",
                    content=self._question,
                    turn_id=turn.id,
                )
                turn.user_message_id = user_message.id
                db.commit()
                counts["created_messages"] = 1
            else:
                counts["reused_messages"] = 1
        assistant = (
            db.get(Message, turn.active_assistant_message_id)
            if turn.active_assistant_message_id is not None
            else None
        )
        self._require_history_message(
            assistant, turn, user, "assistant", allow_missing=True
        )
        source_document = documents_by_key["seven-day-return"]
        citations = [
            {
                "index": 1,
                "docId": str(source_document.id),
                "docName": source_document.source_title or source_document.filename,
                "sourceType": (
                    "url" if source_document.source_url else "file"
                ),
                "fileType": source_document.file_type,
                "url": source_document.source_url,
                "excerpt": self._answer,
            }
        ]
        if assistant is None:
            assistant = self.container.conversations.add_assistant_version(
                db,
                turn=turn,
                user_id=user.id,
                content=self._answer,
                citations=citations,
                message_status="NORMAL",
            )
            counts["created_messages"] += 1
        else:
            counts["reused_messages"] += 1
            assistant.citations_json = json.dumps(citations, ensure_ascii=False)
        assistant.vote = 1
        db.commit()
        return counts

    def _upsert_support_workflow(
        self,
        db: Session,
        user: User,
        documents_by_key: dict[str, KnowledgeDocument],
        *,
        target_cases: int = 36,
    ) -> tuple[int, int]:
        """Seed a realistic, deterministic support queue backed by demo policies."""

        if not inspect(db.get_bind()).has_table("support_cases"):
            return 0, 0

        release = db.scalar(
            select(KnowledgeRelease).where(
                KnowledgeRelease.owner_id == user.id,
                KnowledgeRelease.version == "support-demo-v1",
            )
        )
        document_hashes = [
            item.demo_content_sha256 or hashlib.sha256(item.filename.encode()).hexdigest()
            for item in documents_by_key.values()
        ]
        content_hash = hashlib.sha256("".join(sorted(document_hashes)).encode()).hexdigest()
        if release is None:
            release = KnowledgeRelease(
                owner_id=user.id,
                version="support-demo-v1",
                title="即时零售客服规则基线",
                status="published",
                processing_status="ready",
                content_hash=content_hash,
                retrieval_mode=("hybrid" if self.container.knowledge.vector_indexer else "keyword"),
                published_by=user.id,
                published_at=datetime.utcnow(),
                is_active=True,
                is_demo=True,
            )
            db.add(release)
            db.flush()
        for document in documents_by_key.values():
            membership = db.scalar(
                select(KnowledgeReleaseDocument).where(
                    KnowledgeReleaseDocument.release_id == release.id,
                    KnowledgeReleaseDocument.document_id == document.id,
                )
            )
            if membership is None:
                db.add(
                    KnowledgeReleaseDocument(
                        release_id=release.id,
                        document_id=document.id,
                        document_hash=document.demo_content_sha256 or content_hash,
                        filename_snapshot=document.filename,
                    )
                )

        scenarios = (
            ("生鲜破损退款", "草莓送到后压坏了一半，可以退款吗？优惠券会退回来吗？", "refund", "urgent"),
            ("配送超时处理", "订单已经晚了四十分钟，骑手还没到，怎么处理？", "delivery", "high"),
            ("优惠券使用条件", "满减券和会员折扣可以同时使用吗？", "promotion", "normal"),
            ("缺货替换确认", "牛奶缺货了，能换成同价的低脂奶吗？", "product", "normal"),
            ("临期商品售后", "收到的面包明天就过期，可以申请售后吗？", "refund", "high"),
            ("账号安全核验", "有人索要登录验证码并声称可以代办退款，我应该提供吗？", "account", "urgent"),
            ("发票开具", "即时零售订单在哪里申请电子发票？", "invoice", "low"),
            ("地址修改", "订单已经接单了，还能修改配送地址吗？", "delivery", "high"),
            ("冷藏品温度异常", "酸奶送到时已经不冰了，还能喝吗？", "food_safety", "urgent"),
            ("退款到账时间", "退款审核通过后多久原路返回？", "refund", "normal"),
            ("赠品缺失", "活动页面写了赠品，但订单里没有收到。", "promotion", "normal"),
            ("重复扣款", "同一个订单银行卡显示扣了两次款。", "payment", "urgent"),
            ("鲜活商品退货边界", "商品没有质量问题，但我不想要了，能直接按七日无理由退货吗？", "refund", "high"),
        )
        local_source = db.scalar(select(DataSource).where(
            DataSource.owner_id == user.id,
            DataSource.dataset_key == "local-groceries-shopping-baskets",
        ))
        uci_source = db.scalar(select(DataSource).where(
            DataSource.owner_id == user.id,
            DataSource.dataset_key == "uci-online-retail-ii",
        ))
        grounded_rows: list[tuple[int, str, str, str, str]] = []
        if local_source is not None:
            local_rows = db.execute(
                select(Basket.source_basket_key, Product.name, Product.category)
                .join(CommerceImport, CommerceImport.id == Basket.import_id)
                .join(BasketItem, BasketItem.basket_id == Basket.id)
                .join(Product, Product.id == BasketItem.product_id)
                .where(CommerceImport.data_source_id == local_source.id)
                .order_by(Basket.id, BasketItem.id)
                .limit(300)
            ).all()
            grounded_rows.extend((local_source.id, key, product, product_category, "basket") for key, product, product_category in local_rows)
        if uci_source is not None:
            uci_rows = db.execute(
                select(Basket.source_basket_key, Product.name, Basket.country)
                .join(CommerceImport, CommerceImport.id == Basket.import_id)
                .join(BasketItem, BasketItem.basket_id == Basket.id)
                .join(Product, Product.id == BasketItem.product_id)
                .where(CommerceImport.data_source_id == uci_source.id, Basket.invoice_status == "cancelled")
                .order_by(Basket.id, BasketItem.id)
                .limit(60)
            ).all()
            grounded_rows.extend((uci_source.id, key, product, country or "unknown", "cancellation") for key, product, country in uci_rows)
        created = 0
        reused = 0
        now = datetime.utcnow()
        for index in range(target_cases):
            context_source_id, source_record_key, observed_product, observed_category, context_kind = (
                grounded_rows[index % len(grounded_rows)] if grounded_rows else (None, None, None, "未提供", "basket")
            )
            if context_kind == "cancellation":
                title, question, category, priority = (
                    "公开取消单状态核验",
                    "这条公开交易记录标记为取消，但数据不包含退款原因或到账状态，能确认到什么程度？",
                    "cancellation",
                    "high",
                )
            else:
                fresh_text = f"{observed_category} {observed_product or ''}".lower()
                fresh = any(
                    marker in fresh_text
                    for marker in (
                        "果", "蔬", "肉", "鱼", "鲜", "奶", "熟食",
                        "fruit", "vegetable", "meat", "fish", "dairy",
                    )
                )
                allowed = (0, 4, 8, 9, 12) if fresh else (1, 2, 3, 5, 6, 7, 9, 10, 11)
                title, question, category, priority = scenarios[allowed[index % len(allowed)]]
            if observed_product:
                title = f"{title}｜{observed_product}"
                question = f"我的订单里有“{observed_product}”。{question}"
            lineage = {
                "product": {"provenance": "observed", "source_field": "description" if context_kind == "cancellation" else "product_name"},
                "source_record_key": {"provenance": "observed", "source_field": "invoice" if context_kind == "cancellation" else "basket_key"},
                "question": {"provenance": "synthetic", "method": "scenario-template-v3"},
                "customer_wording": {"provenance": "synthetic", "method": "scenario-template-v3"},
                "issue_reason": {"provenance": "synthetic", "method": "scenario-template-v3"},
                "status": {"provenance": "synthetic", "method": "coverage-matrix"},
                "resolution": {"provenance": "synthetic", "method": "coverage-matrix"},
            }
            if context_kind == "cancellation":
                lineage["invoice_status"] = {"provenance": "observed", "source_field": "invoice_status"}
                lineage["cancellation_reason"] = {"provenance": "synthetic", "method": "unavailable; no reason generated"}
            case_key = f"support-demo-{index + 1:03d}"
            order = self._upsert_order_context(
                db,
                user,
                index=index,
                product_name=observed_product,
                product_category=observed_category,
                issue_category=category,
                cancelled=context_kind == "cancellation",
            )
            support_case = db.scalar(
                select(SupportCase).where(
                    SupportCase.owner_id == user.id,
                    SupportCase.case_key == case_key,
                )
            )
            status = ("pending", "in_progress", "resolved", "escalated")[index % 4]
            if support_case is None:
                support_case = SupportCase(
                    owner_id=user.id,
                    case_key=case_key,
                    customer_name=f"顾客{index + 1:02d}",
                    customer_channel=("web", "app", "store")[index % 3],
                    subject=title,
                    status=status,
                    priority=priority,
                    assignee_id=user.id if status != "pending" else None,
                    labels_json=json.dumps(
                        [category, "即时零售"] + (["policy_review"] if "鲜活商品退货边界" in title else []),
                        ensure_ascii=False,
                    ),
                    unread=status == "pending",
                    resolution_code="policy_explained" if status == "resolved" else None,
                    resolution_note="已依据规则完成答复" if status == "resolved" else None,
                    version=1,
                    is_demo=True,
                    source_data_id=context_source_id,
                    source_record_key=source_record_key,
                    generator_version="retail-support-v3",
                    generator_seed=20260807,
                    field_lineage_json=json.dumps(lineage, ensure_ascii=False),
                    order_id=order.id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(support_case)
                db.flush()
                created += 1
            else:
                reused += 1
                if context_source_id is not None:
                    support_case.source_data_id = context_source_id
                    support_case.source_record_key = source_record_key
                    support_case.generator_version = "retail-support-v3"
                    support_case.generator_seed = 20260807
                    support_case.subject = title
                    support_case.labels_json = json.dumps(
                        [category, "即时零售"] + (["policy_review"] if "鲜活商品退货边界" in title else []),
                        ensure_ascii=False,
                    )
                    support_case.field_lineage_json = json.dumps(lineage, ensure_ascii=False)
                support_case.order_id = order.id
            first_message = db.scalar(
                select(SupportMessage).where(
                    SupportMessage.case_id == support_case.id,
                    SupportMessage.role == "customer",
                )
            )
            if first_message is None:
                db.add(
                    SupportMessage(
                        case_id=support_case.id,
                        role="customer",
                        content=question,
                        sent_to_customer=False,
                        created_at=now,
                    )
                )
                db.add(
                    SupportEvent(
                        owner_id=user.id,
                        case_id=support_case.id,
                        event_type="case_created",
                        payload_json=json.dumps({"category": category}, ensure_ascii=False),
                        is_demo=True,
                        occurred_at=now,
                    )
                )
            elif context_source_id is not None:
                first_message.content = question
            if index < 12 and db.scalar(
                select(ReplySuggestion.id).where(ReplySuggestion.case_id == support_case.id)
            ) is None:
                risk_flags = ["refund_review"] if category in {"refund", "payment", "safety"} else []
                suggestion = ReplySuggestion(
                    case_id=support_case.id,
                    requested_by=user.id,
                    knowledge_release_id=release.id,
                    status="completed",
                    content=f"您好，关于“{title}”，我已根据当前已发布规则为您核实。请保留商品和订单凭证，我们将按售后流程协助处理。",
                    citations_json=json.dumps(
                        [{"title": "即时零售售后与活动规则", "releaseVersion": release.version}],
                        ensure_ascii=False,
                    ),
                    risk_flags_json=json.dumps(risk_flags),
                    model_id="demo-grounded-reply",
                    prompt_version="support-v1",
                    config_snapshot_json=json.dumps({"knowledgeVersion": release.version}),
                    latency_ms=680 + index * 13,
                )
                db.add(suggestion)
                db.flush()
                if index < 9:
                    decision = "edited" if index % 3 == 0 else "accepted"
                    final = suggestion.content + (" 我们会在审核后同步处理进度。" if decision == "edited" else "")
                    db.add(
                        ReplyDecision(
                            suggestion_id=suggestion.id,
                            case_id=support_case.id,
                            actor_id=user.id,
                            decision=decision,
                            final_content=final,
                        )
                    )
                    db.add(
                        SupportMessage(
                            case_id=support_case.id,
                            actor_id=user.id,
                            role="agent",
                            content=final,
                            suggestion_id=suggestion.id,
                            sent_to_customer=True,
                            created_at=now,
                        )
                    )
                    db.add(
                        SupportEvent(
                            owner_id=user.id,
                            case_id=support_case.id,
                            actor_id=user.id,
                            event_type=f"suggestion_{decision}",
                            payload_json=json.dumps({"suggestionId": suggestion.id}),
                            is_demo=True,
                            occurred_at=now,
                        )
                    )
                if index in {0, 4, 8}:
                    db.add(
                        SupportQualityLabel(
                            owner_id=user.id,
                            case_id=support_case.id,
                            suggestion_id=suggestion.id,
                            reviewer_id=user.id,
                            verdict="partially_correct",
                            failure_category="missing_knowledge",
                            severity="high",
                            note="缺少更细的赔付或安全处置边界",
                        )
                    )
        for category, title in (
            ("refund", "补充优惠券随退款返还规则"),
            ("safety", "补充冷藏商品温度异常处置规则"),
            ("promotion", "明确赠品缺失补发条件"),
        ):
            fingerprint = hashlib.sha256(f"demo:{category}:{title}".encode()).hexdigest()
            if db.scalar(
                select(KnowledgeGap.id).where(
                    KnowledgeGap.owner_id == user.id,
                    KnowledgeGap.fingerprint == fingerprint,
                )
            ) is None:
                db.add(
                    KnowledgeGap(
                        owner_id=user.id,
                        fingerprint=fingerprint,
                        title=title,
                        category=category,
                        severity="high",
                        status="open",
                        occurrence_count=3,
                        owner_user_id=user.id,
                        evidence_json="[]",
                        is_demo=True,
                    )
                )
        db.commit()
        return created, reused

    @staticmethod
    def _upsert_order_context(
        db: Session,
        user: User,
        *,
        index: int,
        product_name: str | None,
        product_category: str,
        issue_category: str,
        cancelled: bool,
    ) -> Order:
        """Create deterministic order facts without presenting generated fields as observed."""

        order_no = f"NB-DEMO-{index + 1:03d}"
        customer_key = f"demo-customer-{index + 1:03d}"
        customer = db.scalar(
            select(CustomerSnapshot).where(
                CustomerSnapshot.owner_id == user.id,
                CustomerSnapshot.customer_key == customer_key,
            )
        )
        captured_at = datetime(2026, 8, 7, 8, 0) + timedelta(minutes=index * 17)
        if customer is None:
            customer = CustomerSnapshot(
                owner_id=user.id,
                customer_key=customer_key,
                display_name=f"顾客{index + 1:02d}",
                tier=("新客", "常购顾客", "高价值顾客")[index % 3],
                order_count=1 + (index * 7) % 24,
                refund_count=index % 4,
                lifetime_value_minor=6800 + index * 2190,
                captured_at=captured_at,
                is_demo=True,
                lineage_json=json.dumps(
                    {
                        "allFields": {
                            "provenance": "synthetic",
                            "method": "support-scenario-v1",
                        }
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(customer)
            db.flush()

        order = db.scalar(
            select(Order).where(
                Order.owner_id == user.id,
                Order.order_no == order_no,
            )
        )
        if cancelled:
            order_status = "cancelled"
        elif issue_category == "delivery":
            order_status = "delivering"
        elif issue_category == "refund":
            order_status = "refund_review"
        else:
            order_status = "delivered"
        order_lineage = {
            "productReference": {
                "provenance": "observed" if product_name else "synthetic",
                "source": "verified-retail-snapshot" if product_name else "support-scenario-v1",
            },
            "orderState": {
                "provenance": "synthetic",
                "method": "support-scenario-v1",
            },
            "amount": {
                "provenance": "synthetic",
                "method": "deterministic-price-matrix-v1",
            },
        }
        if order is None:
            order = Order(
                owner_id=user.id,
                order_no=order_no,
                customer_snapshot_id=customer.id,
                status=order_status,
                currency="CNY",
                total_amount_minor=3990 + (index % 8) * 870,
                placed_at=captured_at,
                is_demo=True,
                lineage_json=json.dumps(order_lineage, ensure_ascii=False),
                created_at=captured_at,
                updated_at=captured_at,
            )
            db.add(order)
            db.flush()
        else:
            order.customer_snapshot_id = customer.id
            order.status = order_status
            order.total_amount_minor = 3990 + (index % 8) * 870
            order.placed_at = captured_at
            order.is_demo = True
            order.lineage_json = json.dumps(order_lineage, ensure_ascii=False)

        product = (
            db.scalar(
                select(Product).where(
                    Product.owner_id == user.id,
                    Product.name == product_name,
                )
            )
            if product_name
            else None
        )
        item = db.scalar(
            select(OrderItem).where(OrderItem.order_id == order.id).limit(1)
        )
        item_lineage = {
            "productName": {
                "provenance": "observed" if product_name else "synthetic",
                "source": "verified-retail-snapshot" if product_name else "support-scenario-v1",
            },
            "quantity": {"provenance": "synthetic", "method": "fixed-one"},
            "unitPrice": {
                "provenance": "synthetic",
                "method": "deterministic-price-matrix-v1",
            },
        }
        if item is None:
            item = OrderItem(order_id=order.id)
            db.add(item)
        item.product_id = product.id if product else None
        item.sku = product.source_key if product else f"DEMO-SKU-{index + 1:03d}"
        item.product_name = product_name or f"{product_category or '未分类'}演示商品"
        item.quantity = 1
        item.unit_price_minor = order.total_amount_minor
        item.lineage_json = json.dumps(item_lineage, ensure_ascii=False)

        estimated = captured_at + timedelta(minutes=45)
        fulfillment = db.scalar(
            select(Fulfillment).where(Fulfillment.order_id == order.id).limit(1)
        )
        if fulfillment is None:
            fulfillment = Fulfillment(order_id=order.id)
            db.add(fulfillment)
        fulfillment.status = (
            "cancelled"
            if cancelled
            else ("delayed" if issue_category == "delivery" else "delivered")
        )
        fulfillment.carrier = "邻里配送（演示）"
        fulfillment.tracking_no = None
        fulfillment.estimated_delivery_at = estimated
        fulfillment.delivered_at = (
            None
            if cancelled or issue_category == "delivery"
            else estimated + timedelta(minutes=(index % 4) * 4)
        )
        fulfillment.current_location = None
        fulfillment.updated_at = estimated
        fulfillment.lineage_json = json.dumps(
            {
                "allFields": {
                    "provenance": "synthetic",
                    "method": "support-scenario-v1",
                },
                "currentLocation": {"provenance": "unavailable"},
            },
            ensure_ascii=False,
        )

        refund = db.scalar(select(Refund).where(Refund.order_id == order.id).limit(1))
        if refund is None:
            refund = Refund(order_id=order.id)
            db.add(refund)
        refund.status = "reviewing" if issue_category == "refund" else "not_requested"
        refund.amount_minor = order.total_amount_minor if issue_category == "refund" else 0
        refund.reason = "演示售后场景" if issue_category == "refund" else None
        refund.requested_at = captured_at + timedelta(hours=2) if issue_category == "refund" else None
        refund.resolved_at = None
        refund.lineage_json = json.dumps(
            {
                "allFields": {
                    "provenance": "synthetic",
                    "method": "support-scenario-v1",
                }
            },
            ensure_ascii=False,
        )
        db.flush()
        return order

    def expand_grounded_support(self, db: Session, *, target_cases: int = 360) -> tuple[int, int]:
        """Expand only the complete CLI demo after verified retail snapshots exist."""
        user = self.container.user_repository.get_by_username(db, self.catalog.account.username)
        if user is None or not user.is_demo:
            raise DemoOwnershipError("demo user is missing or not demo-owned")
        documents = list(db.scalars(select(KnowledgeDocument).join(KnowledgeBase).where(
            KnowledgeBase.owner_id == user.id, KnowledgeDocument.demo_content_sha256.is_not(None),
        )))
        return self._upsert_support_workflow(
            db, user, {f"document-{item.id}": item for item in documents}, target_cases=target_cases,
        )

    @staticmethod
    def _require_history_message(
        message: Message | None,
        turn: ConversationTurn,
        user: User,
        role: str,
        *,
        allow_missing: bool,
    ) -> None:
        if message is None and allow_missing:
            return
        if (
            message is None
            or message.user_id != user.id
            or message.conversation_id != turn.conversation_id
            or message.turn_id != turn.id
            or message.role != role
        ):
            raise DemoOwnershipError(
                "ownership identity violation: reused history message mismatch"
            )

    def _storage_root(self) -> Path:
        url = self.container.database.engine.url
        if url.database and url.drivername == "sqlite":
            database_path = Path(os.path.abspath(url.database))
            return database_path.parent / f"{database_path.stem}-demo-files"
        normalized_url = url.render_as_string(hide_password=True)
        digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:16]
        return Path(
            os.path.abspath(Path.cwd() / "data" / f"demo-seed-files-{digest}")
        )

    @staticmethod
    def _legacy_storage_root() -> Path:
        return Path(os.path.abspath(Path.cwd() / "data" / "demo-seed-files"))

    def _require_managed_path(self, path: Path) -> None:
        path_key = self._lexical_key(path)
        roots = (self._storage_root(), self._legacy_storage_root())
        matched_root: Path | None = None
        for root in roots:
            root_key = self._lexical_key(root)
            try:
                common = os.path.commonpath((root_key, path_key))
            except ValueError:
                continue
            if common == root_key and path_key != root_key:
                matched_root = root
                break
        if matched_root is None:
            raise DemoOwnershipError(
                "ownership violation: demo file path escapes managed roots"
            )

        root_stat = self._lstat_or_none(matched_root)
        if root_stat is not None:
            if self._is_link_or_reparse(root_stat) or not stat.S_ISDIR(
                root_stat.st_mode
            ):
                raise DemoOwnershipError(
                    "ownership violation: managed root is not a regular directory"
                )

        relative = Path(
            os.path.relpath(path_key, self._lexical_key(matched_root))
        )
        ancestor = matched_root
        for component in relative.parts[:-1]:
            ancestor /= component
            ancestor_stat = self._lstat_or_none(ancestor)
            if ancestor_stat is None:
                continue
            if self._is_link_or_reparse(ancestor_stat):
                raise DemoOwnershipError(
                    "ownership violation: managed path has a symlink or reparse ancestor"
                )
            if not stat.S_ISDIR(ancestor_stat.st_mode):
                raise DemoOwnershipError(
                    "ownership violation: managed path ancestor is not a directory"
                )

        canonical_root = self._canonical_key(matched_root)
        canonical_path = self._canonical_key(path.parent / ".")
        try:
            canonical_common = os.path.commonpath(
                (canonical_root, canonical_path)
            )
        except ValueError as exc:
            raise DemoOwnershipError(
                "ownership violation: managed file path is on another volume"
            ) from exc
        if canonical_common != canonical_root:
            raise DemoOwnershipError(
                "ownership violation: managed file path escapes canonical root"
            )

    def _require_managed_file_target(self, path: Path):
        self._require_managed_path(path)
        target_stat = self._lstat_or_none(path)
        if target_stat is None:
            return None
        if self._is_link_or_reparse(target_stat):
            if not stat.S_ISLNK(target_stat.st_mode):
                raise DemoOwnershipError(
                    "ownership violation: managed document target is a reparse directory"
                )
            return target_stat
        if not stat.S_ISREG(target_stat.st_mode):
            raise DemoOwnershipError(
                "ownership violation: managed document path is not a regular file"
            )
        return target_stat

    @staticmethod
    def _lexical_key(path: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _canonical_key(path: Path) -> str:
        return os.path.normcase(os.fspath(path.resolve(strict=False)))

    @staticmethod
    def _lstat_or_none(path: Path):
        try:
            return path.lstat()
        except FileNotFoundError:
            return None

    @staticmethod
    def _is_link_or_reparse(path_stat) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return stat.S_ISLNK(path_stat.st_mode) or bool(
            getattr(path_stat, "st_file_attributes", 0) & reparse_flag
        )

    def _shares_regular_file(
        self, path: Path, ordinary_paths: tuple[Path, ...]
    ) -> bool:
        path_key = self._canonical_key(path)
        path_stat = self._lstat_or_none(path)
        for ordinary in ordinary_paths:
            if self._canonical_key(ordinary) == path_key:
                return True
            ordinary_stat = self._lstat_or_none(ordinary)
            if path_stat is not None and ordinary_stat is not None and os.path.samefile(
                path, ordinary
            ):
                return True
        return False

    @staticmethod
    def _delete_ids(db: Session, model, column, identifiers) -> int:
        if not identifiers:
            return 0
        result = db.execute(delete(model).where(column.in_(identifiers)))
        return int(result.rowcount or 0)
