from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.evaluation.models import EvaluationCase, EvaluationDataset


@dataclass(frozen=True, slots=True)
class EvaluationCaseInput:
    question: str
    category: str
    difficulty: str
    knowledge_base_ids: list[int]
    expected_points: list[str]
    expected_document_keys: list[str]
    should_refuse: bool
    case_key: str | None = None
    reference_answer: str | None = None


class EvaluationRepository:
    def create_dataset_with_cases(
        self,
        db: Session,
        *,
        owner_id: int,
        name: str,
        description: str | None,
        is_demo: bool,
        cases: list[EvaluationCaseInput],
    ) -> EvaluationDataset:
        dataset = EvaluationDataset(
            owner_id=owner_id,
            name=name,
            description=description,
            is_demo=is_demo,
        )
        try:
            db.add(dataset)
            db.flush()
            case_keys: set[str] = set()
            for index, case_input in enumerate(cases, start=1):
                self._validate_case(case_input)
                case_key = case_input.case_key or f"case-{index}"
                if case_key in case_keys:
                    raise ValueError("case_key values must be unique within a dataset")
                case_keys.add(case_key)
                dataset.cases.append(
                    EvaluationCase(
                        case_key=case_key,
                        question=case_input.question,
                        category=case_input.category,
                        difficulty=case_input.difficulty,
                        knowledge_base_ids_json=self._encode(case_input.knowledge_base_ids),
                        expected_points_json=self._encode(case_input.expected_points),
                        expected_document_keys_json=self._encode(
                            case_input.expected_document_keys
                        ),
                        should_refuse=case_input.should_refuse,
                        reference_answer=case_input.reference_answer,
                    )
                )
            db.flush()
            db.refresh(dataset)
            db.commit()
            return dataset
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _validate_case(case_input: EvaluationCaseInput) -> None:
        if not case_input.question.strip():
            raise ValueError("question must not be empty")
        if not case_input.expected_points:
            raise ValueError("expected_points must not be empty")

    @staticmethod
    def _encode(values: list[int] | list[str]) -> str:
        return json.dumps(values, ensure_ascii=False, separators=(",", ":"))
