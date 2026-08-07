from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.framework.database import Base, Database
from app.modules.evaluation.models import EvaluationCase, EvaluationDataset
from app.modules.evaluation.repository import EvaluationCaseInput, EvaluationRepository
from app.modules.users.models import User


@pytest.fixture
def db(tmp_path) -> Session:
    database = Database(f"sqlite:///{tmp_path / 'evaluation.db'}")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()
        database.engine.dispose()


@pytest.fixture
def user(db: Session) -> User:
    item = User(username="evaluation-owner", password_hash="hash")
    db.add(item)
    db.commit()
    return item


def test_dataset_persists_structured_cases(db: Session, user: User):
    dataset = EvaluationRepository().create_dataset_with_cases(
        db,
        owner_id=user.id,
        name="商家售后基础集",
        description="退款、退货和物流问题",
        is_demo=True,
        cases=[
            EvaluationCaseInput(
                question="七天无理由退货从哪天开始计算？",
                category="after_sales",
                difficulty="basic",
                knowledge_base_ids=[1],
                expected_points=["从签收商品的次日开始计算"],
                expected_document_keys=["seven-day-return"],
                should_refuse=False,
                reference_answer="七日期间从消费者签收商品的次日开始计算。",
            )
        ],
    )

    assert dataset.id is not None
    assert dataset.is_demo is True
    assert dataset.cases[0].expected_points == ["从签收商品的次日开始计算"]


def test_cases_round_trip_json_lists_and_keep_reference_answer_independent(
    db: Session, user: User
):
    dataset = EvaluationRepository().create_dataset_with_cases(
        db,
        owner_id=user.id,
        name="结构化数据集",
        description=None,
        is_demo=False,
        cases=[
            EvaluationCaseInput(
                case_key="shipping-delay",
                question="物流延迟怎么办？",
                category="logistics",
                difficulty="advanced",
                knowledge_base_ids=[8, 3],
                expected_points=["说明时效", "提供处理路径"],
                expected_document_keys=["delay-policy", "shipping-faq"],
                should_refuse=True,
                reference_answer="这是仅供人工核对的参考回答。",
            )
        ],
    )
    case_id = dataset.cases[0].id

    db.expunge_all()
    persisted = db.get(EvaluationCase, case_id)

    assert persisted is not None
    assert persisted.knowledge_base_ids == [8, 3]
    assert persisted.expected_points == ["说明时效", "提供处理路径"]
    assert persisted.expected_document_keys == ["delay-policy", "shipping-faq"]
    assert persisted.reference_answer == "这是仅供人工核对的参考回答。"


def test_owner_cannot_reuse_dataset_name(db: Session, user: User):
    repository = EvaluationRepository()
    repository.create_dataset_with_cases(
        db,
        owner_id=user.id,
        name="唯一名称",
        description=None,
        is_demo=False,
        cases=[],
    )

    with pytest.raises(IntegrityError):
        repository.create_dataset_with_cases(
            db,
            owner_id=user.id,
            name="唯一名称",
            description=None,
            is_demo=False,
            cases=[],
        )


@pytest.mark.parametrize(
    "invalid_case",
    [
        EvaluationCaseInput(
            question="",
            category="after_sales",
            difficulty="basic",
            knowledge_base_ids=[],
            expected_points=["包含必要要点"],
            expected_document_keys=[],
            should_refuse=False,
        ),
        EvaluationCaseInput(
            question="有效问题",
            category="after_sales",
            difficulty="basic",
            knowledge_base_ids=[],
            expected_points=[],
            expected_document_keys=[],
            should_refuse=False,
        ),
    ],
    ids=["empty-question", "empty-expected-points"],
)
def test_invalid_case_rolls_back_dataset_and_cases(
    db: Session, user: User, invalid_case: EvaluationCaseInput
):
    rollback_events: list[Session] = []

    def record_rollback(session: Session) -> None:
        rollback_events.append(session)

    event.listen(db, "after_rollback", record_rollback)
    with pytest.raises(ValueError):
        try:
            EvaluationRepository().create_dataset_with_cases(
                db,
                owner_id=user.id,
                name="应回滚的数据集",
                description=None,
                is_demo=False,
                cases=[
                    EvaluationCaseInput(
                        question="有效问题",
                        category="after_sales",
                        difficulty="basic",
                        knowledge_base_ids=[],
                        expected_points=["包含必要要点"],
                        expected_document_keys=[],
                        should_refuse=False,
                    ),
                    invalid_case,
                ],
            )
        finally:
            event.remove(db, "after_rollback", record_rollback)

    assert db.query(EvaluationDataset).count() == 0
    assert db.query(EvaluationCase).count() == 0
    assert rollback_events == [db]


def test_duplicate_case_key_in_one_dataset_rolls_back_all_rows(
    db: Session, user: User
):
    duplicate = "same-key"
    with pytest.raises(ValueError, match="case_key"):
        EvaluationRepository().create_dataset_with_cases(
            db,
            owner_id=user.id,
            name="重复案例键",
            description=None,
            is_demo=False,
            cases=[
                EvaluationCaseInput(
                    case_key=duplicate,
                    question="第一个问题",
                    category="after_sales",
                    difficulty="basic",
                    knowledge_base_ids=[],
                    expected_points=["第一个要点"],
                    expected_document_keys=[],
                    should_refuse=False,
                ),
                EvaluationCaseInput(
                    case_key=duplicate,
                    question="第二个问题",
                    category="after_sales",
                    difficulty="basic",
                    knowledge_base_ids=[],
                    expected_points=["第二个要点"],
                    expected_document_keys=[],
                    should_refuse=False,
                ),
            ],
        )

    assert db.query(EvaluationDataset).count() == 0
    assert db.query(EvaluationCase).count() == 0


def test_refresh_failure_does_not_persist_dataset_or_cases(db: Session, user: User):
    def fail_dataset_refresh(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("SELECT EVALUATION_DATASETS"):
            raise RuntimeError("injected dataset refresh failure")

    event.listen(db.bind, "before_cursor_execute", fail_dataset_refresh)
    try:
        with pytest.raises(RuntimeError, match="injected dataset refresh failure"):
            EvaluationRepository().create_dataset_with_cases(
                db,
                owner_id=user.id,
                name="refresh 失败必须回滚",
                description=None,
                is_demo=False,
                cases=[
                    EvaluationCaseInput(
                        question="提交后读取失败怎么办？",
                        category="persistence",
                        difficulty="basic",
                        knowledge_base_ids=[1],
                        expected_points=["事务不能留下部分数据"],
                        expected_document_keys=["atomicity"],
                        should_refuse=False,
                    )
                ],
            )
    finally:
        event.remove(db.bind, "before_cursor_execute", fail_dataset_refresh)

    assert db.query(EvaluationDataset).count() == 0
    assert db.query(EvaluationCase).count() == 0
