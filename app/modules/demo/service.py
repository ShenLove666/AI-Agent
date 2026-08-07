"""Deterministic, offline demo data seeding and ownership-safe cleanup."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.modules.conversations.models import (
    ChatRequestRun,
    Conversation,
    ConversationTurn,
    Message,
)
from app.modules.demo.catalog import DemoCatalog, load_demo_catalog
from app.modules.evaluation.models import EvaluationCase, EvaluationDataset
from app.modules.evaluation.repository import EvaluationCaseInput, EvaluationRepository
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
from app.modules.users.models import User


class DemoSeedError(RuntimeError):
    """Raised when seeding cannot finish without leaving partial demo data."""


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
            )
        )


class DemoSeedService:
    """Create and remove the bundled demo strictly within ``User.is_demo``."""

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
        if reset:
            self.clear(db)

        counts = {
            field: 0
            for field in DemoSeedResult.__dataclass_fields__
        }
        try:
            user, created = self._upsert_user(db, password)
            counts["created_users" if created else "reused_users"] += 1

            bases_by_key: dict[str, KnowledgeBase] = {}
            for catalog_base in self.catalog.knowledge_bases:
                item, created = self._upsert_knowledge_base(
                    db, user, catalog_base.key, catalog_base.name, catalog_base.description
                )
                bases_by_key[catalog_base.key] = item
                key = (
                    "created_knowledge_bases"
                    if created
                    else "reused_knowledge_bases"
                )
                counts[key] += 1

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
                if document.status == "indexed":
                    continue
                ingested = self.container.knowledge.ingest_document(db, document.id)
                if ingested.status != "indexed":
                    raise DemoSeedError(
                        ingested.error_message
                        or f"failed to index demo document {ingested.filename}"
                    )

            dataset, dataset_created, created_cases, reused_cases = (
                self._upsert_evaluation_dataset(db, user, bases_by_key)
            )
            del dataset
            counts[
                "created_evaluation_datasets"
                if dataset_created
                else "reused_evaluation_datasets"
            ] += 1
            counts["created_evaluation_cases"] += created_cases
            counts["reused_evaluation_cases"] += reused_cases

            history_counts = self._upsert_history(db, user, bases_by_key)
            for key, value in history_counts.items():
                counts[key] += value
            return DemoSeedResult(**counts)
        except Exception as exc:
            db.rollback()
            self.clear(db)
            if isinstance(exc, DemoSeedError):
                raise
            raise DemoSeedError(str(exc)) from exc

    def clear(self, db: Session) -> DemoClearResult:
        """Delete demo-owned rows first, then only their collected external IDs."""

        demo_user_ids = list(
            db.scalars(select(User.id).where(User.is_demo.is_(True)))
        )
        if not demo_user_ids:
            return DemoClearResult()

        base_ids = list(
            db.scalars(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.owner_id.in_(demo_user_ids)
                )
            )
        )
        document_rows = list(
            db.execute(
                select(KnowledgeDocument.id, KnowledgeDocument.storage_path).where(
                    KnowledgeDocument.uploader_id.in_(demo_user_ids)
                )
            )
        )
        document_ids = [row.id for row in document_rows]
        storage_paths = [Path(row.storage_path) for row in document_rows]
        dataset_ids = list(
            db.scalars(
                select(EvaluationDataset.id).where(
                    EvaluationDataset.owner_id.in_(demo_user_ids)
                )
            )
        )
        conversation_ids = list(
            db.scalars(
                select(Conversation.id).where(
                    Conversation.user_id.in_(demo_user_ids)
                )
            )
        )
        turn_ids = list(
            db.scalars(
                select(ConversationTurn.id).where(
                    ConversationTurn.conversation_id.in_(conversation_ids)
                )
            )
        ) if conversation_ids else []
        trace_ids = list(
            db.scalars(
                select(RagTraceRun.id).where(
                    RagTraceRun.user_id.in_(demo_user_ids)
                )
            )
        )

        counts = {
            "removed_request_runs": self._delete_count(
                db, ChatRequestRun, ChatRequestRun.user_id.in_(demo_user_ids)
            ),
            "removed_trace_nodes": self._delete_count(
                db, RagTraceNode, RagTraceNode.run_id.in_(trace_ids)
            ) if trace_ids else 0,
            "removed_trace_runs": self._delete_count(
                db, RagTraceRun, RagTraceRun.id.in_(trace_ids)
            ) if trace_ids else 0,
        }

        if turn_ids:
            db.execute(
                update(ConversationTurn)
                .where(ConversationTurn.id.in_(turn_ids))
                .values(user_message_id=None, active_assistant_message_id=None)
            )
            db.execute(
                update(Message)
                .where(Message.turn_id.in_(turn_ids))
                .values(turn_id=None)
            )
        counts["removed_messages"] = (
            self._delete_count(
                db, Message, Message.conversation_id.in_(conversation_ids)
            )
            if conversation_ids
            else 0
        )
        counts["removed_turns"] = (
            self._delete_count(
                db, ConversationTurn, ConversationTurn.id.in_(turn_ids)
            )
            if turn_ids
            else 0
        )
        counts["removed_conversations"] = (
            self._delete_count(
                db, Conversation, Conversation.id.in_(conversation_ids)
            )
            if conversation_ids
            else 0
        )
        counts["removed_evaluation_cases"] = (
            self._delete_count(
                db, EvaluationCase, EvaluationCase.dataset_id.in_(dataset_ids)
            )
            if dataset_ids
            else 0
        )
        counts["removed_evaluation_datasets"] = (
            self._delete_count(
                db, EvaluationDataset, EvaluationDataset.id.in_(dataset_ids)
            )
            if dataset_ids
            else 0
        )
        counts["removed_chunks"] = (
            self._delete_count(
                db, KnowledgeChunk, KnowledgeChunk.document_id.in_(document_ids)
            )
            if document_ids
            else 0
        )
        counts["removed_documents"] = (
            self._delete_count(
                db, KnowledgeDocument, KnowledgeDocument.id.in_(document_ids)
            )
            if document_ids
            else 0
        )
        counts["removed_knowledge_bases"] = (
            self._delete_count(
                db, KnowledgeBase, KnowledgeBase.id.in_(base_ids)
            )
            if base_ids
            else 0
        )
        counts["removed_users"] = self._delete_count(
            db, User, User.id.in_(demo_user_ids)
        )
        db.commit()

        removed_vectors = 0
        removed_files = 0
        cleanup_errors: list[str] = []
        vector_indexer = self.container.knowledge.vector_indexer
        if vector_indexer is not None:
            for document_id in document_ids:
                try:
                    asyncio.run(vector_indexer.store.delete_document(document_id))
                    removed_vectors += 1
                except Exception as exc:  # external cleanup is best-effort and reported
                    cleanup_errors.append(f"vector document {document_id}: {exc}")

        storage_root = self._storage_root()
        for path in storage_paths:
            try:
                resolved = path.resolve()
                resolved.relative_to(storage_root)
                still_referenced = db.scalar(
                    select(func.count(KnowledgeDocument.id)).where(
                        KnowledgeDocument.storage_path == str(path)
                    )
                )
                if not still_referenced and resolved.is_file():
                    resolved.unlink()
                    removed_files += 1
            except (OSError, ValueError) as exc:
                cleanup_errors.append(f"file {path}: {exc}")
        try:
            storage_root.rmdir()
        except OSError:
            pass

        return DemoClearResult(
            **counts,
            removed_files=removed_files,
            removed_vectors=removed_vectors,
            external_cleanup_errors=tuple(cleanup_errors),
        )

    def _upsert_user(self, db: Session, password: str) -> tuple[User, bool]:
        user = self.container.user_repository.get_by_username(
            db, self.catalog.account.username
        )
        if user is not None:
            if not user.is_demo:
                raise DemoSeedError(
                    "refusing to adopt an existing non-demo user with the demo username"
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
        return (
            self.container.knowledge.create_base(
                db, user.id, stable_name, description
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
        item = db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == base.id,
                KnowledgeDocument.uploader_id == user.id,
                KnowledgeDocument.filename == filename,
            )
        )
        created = item is None
        if item is None:
            item = self.container.knowledge.create_document(
                db,
                base_id=base.id,
                uploader_id=user.id,
                filename=filename,
                storage_path=str(destination),
                file_size=source_path.stat().st_size,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file():
            shutil.copyfile(source_path, destination)
        item.storage_path = str(destination)
        item.file_size = destination.stat().st_size
        item.content_origin = source.content_origin
        item.source_url = source.source_url
        item.source_publisher = source.source_publisher
        item.source_retrieved_at = source.source_retrieved_at
        item.source_usage_note = source.source_usage_note
        db.commit()
        return item, created

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
            raise DemoSeedError("refusing to adopt a non-demo evaluation dataset")
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
        self, db: Session, user: User, bases_by_key: dict[str, KnowledgeBase]
    ) -> dict[str, int]:
        counts = {
            "created_conversations": 0,
            "reused_conversations": 0,
            "created_turns": 0,
            "reused_turns": 0,
            "created_messages": 0,
            "reused_messages": 0,
        }
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.title == self._conversation_title,
            )
        )
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
            user_message = db.get(Message, turn.user_message_id)
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
        if assistant is None:
            assistant = self.container.conversations.add_assistant_version(
                db,
                turn=turn,
                user_id=user.id,
                content=self._answer,
                citations=[
                    {
                        "documentKey": "seven-day-return",
                        "title": "网络购买商品七日无理由退货规则摘要",
                    }
                ],
                message_status="NORMAL",
            )
            counts["created_messages"] += 1
        else:
            counts["reused_messages"] += 1
        assistant.vote = 1
        db.commit()
        return counts

    def _storage_root(self) -> Path:
        database_path = self.container.database.engine.url.database
        if database_path and self.container.database.engine.url.drivername == "sqlite":
            path = Path(database_path).resolve()
            return (path.parent / f"{path.stem}-demo-files").resolve()
        return (Path.cwd() / "data" / "demo-seed-files").resolve()

    @staticmethod
    def _delete_count(db: Session, model, condition) -> int:
        result = db.execute(delete(model).where(condition))
        return int(result.rowcount or 0)
