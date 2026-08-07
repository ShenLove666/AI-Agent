from __future__ import annotations

import copy
import errno
import json
import urllib.request
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.cli as cli
import app.modules.demo.catalog as demo_catalog
from app.application import create_app
from app.framework.config import Settings
from app.framework.database import Base, Database
from app.modules.conversations.models import (
    ChatRequestRun,
    Conversation,
    ConversationTurn,
    Message,
)
from app.modules.demo.catalog import DemoCatalogError, load_demo_catalog
from app.modules.demo.service import DemoSeedError, DemoSeedService
from app.modules.evaluation.models import EvaluationCase, EvaluationDataset
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.modules.rag.trace_models import RagTraceNode, RagTraceRun
from app.modules.users.models import User
from app.modules.vector.indexer import VectorIndexer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("EMBED_MODEL_PATH", raising=False)
    database_url = f"sqlite:///{tmp_path / 'demo-metadata.db'}"
    item = create_app(Settings(database_url=database_url))
    Base.metadata.create_all(item.state.container.database.engine)
    try:
        yield item
    finally:
        item.state.container.database.engine.dispose()


@pytest.fixture
def db(app) -> Session:
    session = app.state.container.database.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db: Session) -> User:
    item = User(username="owner", password_hash="hash")
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def knowledge_base(db: Session, user: User) -> KnowledgeBase:
    item = KnowledgeBase(owner_id=user.id, name="demo")
    db.add(item)
    db.flush()
    return item


def test_regular_user_and_upload_are_not_demo_or_public_by_default(db: Session):
    user = User(username="owner", password_hash="hash")
    db.add(user)
    db.flush()

    assert user.is_demo is False

    knowledge_base = KnowledgeBase(owner_id=user.id, name="uploads")
    db.add(knowledge_base)
    db.flush()
    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        uploader_id=user.id,
        filename="owner-upload.txt",
        file_type="txt",
        storage_path="uploads/owner-upload.txt",
    )
    db.add(document)
    db.commit()
    document_id = document.id

    db.expunge_all()
    persisted = db.get(KnowledgeDocument, document_id)

    assert persisted is not None
    assert persisted.content_origin == "user_upload"


def test_public_summary_keeps_provenance(
    db: Session, knowledge_base: KnowledgeBase, user: User
):
    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        uploader_id=user.id,
        filename="return-summary.md",
        file_type="md",
        storage_path="resources/demo/documents/seven-day-return-summary.md",
        content_origin="public_summary",
        source_url=(
            "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
            "art_26ca8fe29e184edd899fa0a7a060d935.html"
        ),
        source_publisher="国家市场监督管理总局",
        source_retrieved_at=date(2026, 8, 7),
        source_usage_note="原创摘要，仅用于本地演示；原文以来源页面为准。",
    )
    db.add(document)
    db.commit()
    document_id = document.id

    db.expunge_all()
    persisted = db.get(KnowledgeDocument, document_id)

    assert persisted is not None
    assert persisted.content_origin == "public_summary"
    assert persisted.source_url == (
        "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
        "art_26ca8fe29e184edd899fa0a7a060d935.html"
    )
    assert persisted.source_publisher == "国家市场监督管理总局"
    assert persisted.source_retrieved_at == date(2026, 8, 7)
    assert persisted.source_usage_note == "原创摘要，仅用于本地演示；原文以来源页面为准。"


def test_document_rejects_unknown_content_origin(
    knowledge_base: KnowledgeBase, user: User
):
    with pytest.raises(ValueError, match="content_origin must be one of"):
        KnowledgeDocument(
            knowledge_base_id=knowledge_base.id,
            uploader_id=user.id,
            filename="unknown.txt",
            file_type="txt",
            storage_path="unknown.txt",
            content_origin="partner_upload",
        )


def _valid_catalog_payload() -> dict:
    return {
        "account": {
            "key": "merchant-demo-owner",
            "username": "merchant-demo",
            "display_name": "商家售后演示账号",
        },
        "knowledge_bases": [
            {
                "key": "merchant-support",
                "name": "商家售后知识库",
                "description": "演示知识库",
                "document_keys": ["return-rules"],
            }
        ],
        "documents": [
            {
                "key": "return-rules",
                "title": "退货规则摘要",
                "local_path": "documents/return-rules.md",
                "content_origin": "public_summary",
                "source_url": "https://example.test/official-return-rules",
                "source_publisher": "示例监管机构",
                "source_retrieved_at": "2026-08-07",
                "source_usage_note": "项目原创摘要，官方原文优先。",
            }
        ],
        "evaluation_dataset": {
            "key": "merchant-support-baseline",
            "name": "商家售后基础评测集",
            "description": "演示评测集",
            "cases_path": "evaluation/cases.json",
        },
    }


def _valid_cases_payload() -> dict:
    return {
        "cases": [
            {
                "key": "return-window",
                "question": "退货期限如何计算？",
                "category": "return_window",
                "difficulty": "basic",
                "expected_points": ["说明起算时间"],
                "expected_document_keys": ["return-rules"],
                "should_refuse": False,
                "reference_answer": "按规则说明起算时间。",
            }
        ]
    }


def _write_catalog_fixture(
    root: Path,
    *,
    catalog_payload: dict | None = None,
    cases_payload: dict | None = None,
) -> Path:
    catalog_payload = copy.deepcopy(catalog_payload or _valid_catalog_payload())
    cases_payload = copy.deepcopy(cases_payload or _valid_cases_payload())
    (root / "documents").mkdir(parents=True)
    (root / "evaluation").mkdir()
    (root / "documents" / "return-rules.md").write_text(
        "fixture", encoding="utf-8"
    )
    (root / "catalog.json").write_text(
        json.dumps(catalog_payload, ensure_ascii=False), encoding="utf-8"
    )
    (root / "evaluation" / "cases.json").write_text(
        json.dumps(cases_payload, ensure_ascii=False), encoding="utf-8"
    )
    return root


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=False)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314 or exc.errno in {
            errno.EACCES,
            errno.EPERM,
        }:
            pytest.skip(
                f"file symlink permission unavailable on this Windows environment: {exc}"
            )
        raise


def test_demo_catalog_has_unique_stable_keys_and_valid_local_files():
    catalog = load_demo_catalog(PROJECT_ROOT / "resources" / "demo")

    assert len({item.key for item in catalog.documents}) == len(catalog.documents)
    assert all((catalog.root / item.local_path).is_file() for item in catalog.documents)
    assert all(
        item.source_url
        for item in catalog.documents
        if item.content_origin == "public_summary"
    )


def test_demo_catalog_rejects_manifest_symlink_escape(tmp_path: Path):
    root = _write_catalog_fixture(tmp_path / "demo")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_manifest = outside / "catalog.json"
    outside_payload = _valid_catalog_payload()
    outside_payload["account"]["username"] = "outside-manifest"
    outside_manifest.write_text(
        json.dumps(outside_payload, ensure_ascii=False), encoding="utf-8"
    )
    manifest_link = root / "catalog.json"
    manifest_link.unlink()
    _symlink_or_skip(manifest_link, outside_manifest)

    with pytest.raises(DemoCatalogError, match="manifest|catalog.json|escapes"):
        load_demo_catalog(root)


def test_demo_catalog_rejects_cases_replaced_after_validation(
    tmp_path: Path, monkeypatch
):
    root = _write_catalog_fixture(tmp_path / "demo")
    outside_cases = tmp_path / "outside-cases.json"
    outside_payload = _valid_cases_payload()
    outside_payload["cases"][0]["key"] = "outside-case"
    outside_payload["cases"][0]["question"] = "EXTERNAL CONTENT"
    outside_cases.write_text(
        json.dumps(outside_payload, ensure_ascii=False), encoding="utf-8"
    )
    local_cases = root / "evaluation" / "cases.json"
    real_resolve = demo_catalog._resolve_local_file
    swapped = False

    def resolve_then_swap(
        catalog_root: Path, relative_path: Path, *, field_name: str
    ):
        nonlocal swapped
        resolved = real_resolve(
            catalog_root, relative_path, field_name=field_name
        )
        if field_name == "cases_path" and not swapped:
            outside_cases.replace(local_cases)
            swapped = True
        return resolved

    monkeypatch.setattr(demo_catalog, "_resolve_local_file", resolve_then_swap)

    with pytest.raises(DemoCatalogError, match="cases_path|changed|identity|symlink"):
        load_demo_catalog(root)
    assert swapped is True


@pytest.mark.parametrize(
    ("invalid_path", "field"),
    [
        ("C:/outside/return-rules.md", "local_path"),
        ("../outside/return-rules.md", "local_path"),
        ("/outside/cases.json", "cases_path"),
        ("evaluation/../outside.json", "cases_path"),
    ],
    ids=[
        "absolute-document",
        "traversing-document",
        "absolute-cases",
        "traversing-cases",
    ],
)
def test_demo_catalog_rejects_unsafe_local_paths(
    tmp_path: Path, invalid_path: str, field: str
):
    payload = _valid_catalog_payload()
    if field == "local_path":
        payload["documents"][0][field] = invalid_path
    else:
        payload["evaluation_dataset"][field] = invalid_path
    root = _write_catalog_fixture(tmp_path / "demo", catalog_payload=payload)

    with pytest.raises(DemoCatalogError, match=field):
        load_demo_catalog(root)


@pytest.mark.parametrize(
    "missing_field",
    ["source_url", "source_publisher", "source_retrieved_at", "source_usage_note"],
)
def test_demo_catalog_rejects_public_summary_without_provenance(
    tmp_path: Path, missing_field: str
):
    payload = _valid_catalog_payload()
    del payload["documents"][0][missing_field]
    root = _write_catalog_fixture(tmp_path / "demo", catalog_payload=payload)

    with pytest.raises(DemoCatalogError, match=missing_field):
        load_demo_catalog(root)


def test_demo_catalog_rejects_unknown_content_origin(tmp_path: Path):
    payload = _valid_catalog_payload()
    payload["documents"][0]["content_origin"] = "partner_upload"
    root = _write_catalog_fixture(tmp_path / "demo", catalog_payload=payload)

    with pytest.raises(DemoCatalogError, match="content_origin"):
        load_demo_catalog(root)


def test_demo_catalog_rejects_public_summary_with_malformed_source_url(
    tmp_path: Path,
):
    payload = _valid_catalog_payload()
    payload["documents"][0]["source_url"] = "https:///missing-host"
    root = _write_catalog_fixture(tmp_path / "demo", catalog_payload=payload)

    with pytest.raises(DemoCatalogError, match="source_url"):
        load_demo_catalog(root)


@pytest.mark.parametrize(
    "duplicate_target", ["document", "knowledge_base", "case"], ids=str
)
def test_demo_catalog_rejects_duplicate_stable_keys(
    tmp_path: Path, duplicate_target: str
):
    payload = _valid_catalog_payload()
    cases = _valid_cases_payload()
    if duplicate_target == "document":
        payload["documents"].append(copy.deepcopy(payload["documents"][0]))
    elif duplicate_target == "knowledge_base":
        payload["knowledge_bases"].append(
            copy.deepcopy(payload["knowledge_bases"][0])
        )
    else:
        cases["cases"].append(copy.deepcopy(cases["cases"][0]))
    root = _write_catalog_fixture(
        tmp_path / "demo", catalog_payload=payload, cases_payload=cases
    )

    with pytest.raises(DemoCatalogError, match="duplicate"):
        load_demo_catalog(root)


@pytest.mark.parametrize(
    "reference_owner", ["knowledge_base", "evaluation_case"], ids=str
)
def test_demo_catalog_rejects_unknown_document_references(
    tmp_path: Path, reference_owner: str
):
    payload = _valid_catalog_payload()
    cases = _valid_cases_payload()
    if reference_owner == "knowledge_base":
        payload["knowledge_bases"][0]["document_keys"] = ["missing-document"]
    else:
        cases["cases"][0]["expected_document_keys"] = ["missing-document"]
    root = _write_catalog_fixture(
        tmp_path / "demo", catalog_payload=payload, cases_payload=cases
    )

    with pytest.raises(DemoCatalogError, match="missing-document"):
        load_demo_catalog(root)


def test_demo_catalog_is_deeply_immutable(tmp_path: Path):
    catalog = load_demo_catalog(_write_catalog_fixture(tmp_path / "demo"))

    with pytest.raises(ValidationError):
        catalog.documents[0].title = "changed"
    with pytest.raises(AttributeError):
        catalog.evaluation_cases[0].expected_points.append("changed")


def test_demo_catalog_load_never_accesses_network(tmp_path: Path, monkeypatch):
    root = _write_catalog_fixture(tmp_path / "demo")

    def reject_network(*_args, **_kwargs):
        raise AssertionError("catalog loading must remain offline")

    monkeypatch.setattr(urllib.request, "urlopen", reject_network)

    assert load_demo_catalog(root).documents[0].source_url.startswith("https://")


def test_bundled_evaluation_cases_cover_merchant_support_topics():
    catalog = load_demo_catalog(PROJECT_ROOT / "resources" / "demo")
    case_keys = {case.key for case in catalog.evaluation_cases}

    assert len(catalog.evaluation_cases) >= 12
    assert {
        "return-window-calculation",
        "excluded-customized-goods",
        "refund-timing",
        "return-shipping-cost",
        "gift-return",
        "coupon-restoration",
        "merchant-identity-disclosure",
        "live-commerce-operator-duty",
        "fictional-store-response-sla",
        "out-of-scope-weather",
        "refuse-fabricated-refund-proof",
    } <= case_keys
    assert all(case.expected_points for case in catalog.evaluation_cases)
    assert all(
        isinstance(case.expected_document_keys, tuple)
        for case in catalog.evaluation_cases
    )
    assert any(case.should_refuse for case in catalog.evaluation_cases)


def _create_real_user_graph(db: Session, storage_path: Path) -> dict[type, int | str]:
    storage_path.write_text("ordinary user file", encoding="utf-8")
    real = User(username="real-user", password_hash="hash", is_demo=False)
    db.add(real)
    db.flush()
    knowledge_base = KnowledgeBase(owner_id=real.id, name="real knowledge base")
    db.add(knowledge_base)
    db.flush()
    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        uploader_id=real.id,
        filename="real.txt",
        file_type="txt",
        storage_path=str(storage_path),
        status="indexed",
    )
    db.add(document)
    db.flush()
    chunk = KnowledgeChunk(
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        position=0,
        content="ordinary user chunk",
    )
    dataset = EvaluationDataset(
        owner_id=real.id,
        name="real dataset",
        description="must survive demo clear",
        is_demo=False,
    )
    db.add_all([chunk, dataset])
    db.flush()
    case = EvaluationCase(
        dataset_id=dataset.id,
        case_key="real-case",
        question="real question",
        category="real",
        difficulty="basic",
        expected_points_json='["real point"]',
        expected_document_keys_json="[]",
    )
    conversation = Conversation(
        id=str(uuid.uuid4()), user_id=real.id, title="real conversation"
    )
    db.add_all([case, conversation])
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        sequence=1,
        status="completed",
        knowledge_base_ids_json=f"[{knowledge_base.id}]",
    )
    db.add(turn)
    db.flush()
    user_message = Message(
        conversation_id=conversation.id,
        user_id=real.id,
        turn_id=turn.id,
        role="user",
        content="real user message",
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=real.id,
        turn_id=turn.id,
        version=1,
        role="assistant",
        content="real assistant message",
        vote=-1,
    )
    db.add_all([user_message, assistant_message])
    db.flush()
    turn.user_message_id = user_message.id
    turn.active_assistant_message_id = assistant_message.id
    request_run = ChatRequestRun(
        user_id=real.id,
        request_id="real-request",
        request_fingerprint="real-fingerprint",
        conversation_id=conversation.id,
        turn_id=turn.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        status="completed",
    )
    trace = RagTraceRun(
        id=uuid.uuid4().hex,
        user_id=real.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        query="real trace",
        status="completed",
    )
    db.add_all([request_run, trace])
    db.flush()
    trace_node = RagTraceNode(
        run_id=trace.id,
        name="real node",
        status="completed",
        elapsed_ms=1.0,
    )
    db.add(trace_node)
    db.commit()
    return {
        User: real.id,
        KnowledgeBase: knowledge_base.id,
        KnowledgeDocument: document.id,
        KnowledgeChunk: chunk.id,
        EvaluationDataset: dataset.id,
        EvaluationCase: case.id,
        Conversation: conversation.id,
        ConversationTurn: turn.id,
        Message: assistant_message.id,
        ChatRequestRun: request_run.id,
        RagTraceRun: trace.id,
        RagTraceNode: trace_node.id,
    }


def test_seed_demo_is_idempotent_and_clear_preserves_every_real_user_record(
    app, db: Session, tmp_path: Path
):
    real_file = tmp_path / "real-user.txt"
    real_ids = _create_real_user_graph(db, real_file)
    service = DemoSeedService(app.state.container)

    first = service.seed(db, password="StrongDemo123!")
    second = service.seed(db, password="StrongDemo123!")

    assert first.created_documents == 3
    assert second.created_documents == 0
    assert second.reused_documents == 3
    assert second.reused_evaluation_cases == 14
    assert db.scalar(select(func.count(User.id)).where(User.is_demo.is_(True))) == 1
    assert db.scalar(select(func.count(KnowledgeDocument.id))) == 4
    assert db.scalar(select(func.count(EvaluationDataset.id))) == 2
    assert db.scalar(select(func.count(EvaluationCase.id))) == 15

    demo_user = db.scalar(select(User).where(User.is_demo.is_(True)))
    demo_conversation = db.scalar(
        select(Conversation).where(Conversation.user_id == demo_user.id)
    )
    demo_turn = db.scalar(
        select(ConversationTurn).where(
            ConversationTurn.conversation_id == demo_conversation.id
        )
    )
    demo_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == demo_conversation.id)
            .order_by(Message.id)
        )
    )
    assert demo_conversation.title == "七日无理由退货咨询示例"
    assert demo_turn.status == "completed"
    assert [message.role for message in demo_messages] == ["user", "assistant"]
    assert demo_messages[1].vote == 1
    assert demo_turn.active_assistant_message_id == demo_messages[1].id

    demo_files = {
        Path(path)
        for path in db.scalars(
            select(KnowledgeDocument.storage_path).join(
                User, KnowledgeDocument.uploader_id == User.id
            ).where(User.is_demo.is_(True))
        )
    }
    assert len(demo_files) == 3
    assert all(path.is_file() for path in demo_files)

    cleared = service.clear(db)

    assert cleared.removed_documents == 3
    assert cleared.removed_files == 3
    assert cleared.removed_users == 1
    assert db.scalar(select(func.count(User.id)).where(User.is_demo.is_(True))) == 0
    for model, identifier in real_ids.items():
        assert db.get(model, identifier) is not None, model.__name__
    assert real_file.read_text(encoding="utf-8") == "ordinary user file"
    assert all(not path.exists() for path in demo_files)


class _OfflineEmbeddingModel:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1)] for index, _text in enumerate(texts)]


class _FailThirdDocumentStore:
    def __init__(self):
        self.upsert_calls = 0
        self.records = {}

    async def upsert(self, records) -> None:
        self.upsert_calls += 1
        if self.upsert_calls == 3:
            raise RuntimeError("injected vector index failure")
        self.records.update({record.id: record for record in records})

    async def delete_document(self, document_id: int) -> None:
        self.records = {
            key: record
            for key, record in self.records.items()
            if record.document_id != document_id
        }


def test_seed_vector_failure_removes_partial_demo_graph_and_vectors(
    app, db: Session
):
    store = _FailThirdDocumentStore()
    app.state.container.knowledge.vector_indexer = VectorIndexer(
        _OfflineEmbeddingModel(), store
    )

    with pytest.raises(DemoSeedError, match="injected vector index failure"):
        DemoSeedService(app.state.container).seed(
            db, password="StrongDemo123!"
        )

    assert store.upsert_calls == 3
    assert store.records == {}
    assert db.scalar(select(func.count(User.id)).where(User.is_demo.is_(True))) == 0
    assert db.scalar(select(func.count(KnowledgeBase.id))) == 0
    assert db.scalar(select(func.count(KnowledgeDocument.id))) == 0
    assert db.scalar(select(func.count(KnowledgeChunk.id))) == 0
    assert db.scalar(select(func.count(EvaluationDataset.id))) == 0
    assert db.scalar(select(func.count(EvaluationCase.id))) == 0


def test_demo_cli_uses_named_password_env_and_requires_yes_for_noninteractive_clear(
    tmp_path: Path, monkeypatch, capsys
):
    database_url = f"sqlite:///{tmp_path / 'cli-demo.db'}"
    monkeypatch.setenv("DB_URL", database_url)
    monkeypatch.setenv("CUSTOM_DEMO_PASSWORD", "StrongDemo123!")

    assert cli.main(
        ["seed-demo", "--password-env", "CUSTOM_DEMO_PASSWORD"]
    ) == 0
    assert cli.main(
        ["seed-demo", "--password-env", "CUSTOM_DEMO_PASSWORD"]
    ) == 0
    seed_output = capsys.readouterr().out
    assert "created_documents=3" in seed_output
    assert "reused_documents=3" in seed_output

    monkeypatch.setattr(
        cli.sys, "stdin", SimpleNamespace(isatty=lambda: False)
    )
    assert cli.main(["clear-demo"]) == 2
    database = Database(database_url)
    with database.session_factory() as db:
        assert db.scalar(
            select(func.count(User.id)).where(User.is_demo.is_(True))
        ) == 1

    assert cli.main(["clear-demo", "--yes"]) == 0
    clear_output = capsys.readouterr().out
    assert "removed_records=" in clear_output
    assert "removed_files=3" in clear_output
    with database.session_factory() as db:
        assert db.scalar(
            select(func.count(User.id)).where(User.is_demo.is_(True))
        ) == 0
    database.engine.dispose()


def test_demo_cli_rejects_short_password_before_seeding(
    tmp_path: Path, monkeypatch, capsys
):
    database_url = f"sqlite:///{tmp_path / 'weak-password.db'}"
    monkeypatch.setenv("DB_URL", database_url)
    monkeypatch.setenv("WEAK_DEMO_PASSWORD", "short")

    assert cli.main(
        ["seed-demo", "--password-env", "WEAK_DEMO_PASSWORD"]
    ) == 2
    assert "at least 10" in capsys.readouterr().err


def test_demo_cli_prompts_with_getpass_when_named_env_is_absent(
    tmp_path: Path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'prompted-password.db'}"
    monkeypatch.setenv("DB_URL", database_url)
    monkeypatch.delenv("ABSENT_DEMO_PASSWORD", raising=False)
    prompts: list[str] = []

    def prompted(prompt: str) -> str:
        prompts.append(prompt)
        return "StrongDemo123!"

    monkeypatch.setattr(cli.getpass, "getpass", prompted)

    assert cli.main(
        ["seed-demo", "--password-env", "ABSENT_DEMO_PASSWORD"]
    ) == 0
    assert prompts == ["Demo password: "]
