"""Typed, offline loader for the bundled merchant-support demo catalog."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

StableKey = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
ContentOrigin = Literal["user_upload", "public_summary", "synthetic"]
_HTTP_URL_VALIDATOR = TypeAdapter(AnyHttpUrl)


class DemoCatalogError(ValueError):
    """Raised when bundled demo metadata or a referenced local file is invalid."""


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _validate_relative_path(value: object, field_name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError(f"{field_name} must be a relative local path")
    raw = str(value)
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise ValueError(f"{field_name} must remain under the demo catalog root")
    if not raw.strip() or raw in {".", "./", ".\\"}:
        raise ValueError(f"{field_name} must name a local file")
    return Path(raw)


class DemoAccount(_ImmutableModel):
    key: StableKey
    username: Annotated[str, Field(min_length=1, max_length=50)]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]


class DemoSource(_ImmutableModel):
    key: StableKey
    title: Annotated[str, Field(min_length=1)]
    local_path: Path
    content_origin: ContentOrigin
    source_url: str | None = None
    source_publisher: str | None = None
    source_retrieved_at: date | None = None
    source_usage_note: str | None = None

    @field_validator("local_path", mode="before")
    @classmethod
    def validate_local_path(cls, value: object) -> Path:
        return _validate_relative_path(value, "local_path")

    @field_validator(
        "source_url", "source_publisher", "source_usage_note", mode="before"
    )
    @classmethod
    def reject_blank_provenance(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_public_summary_provenance(self) -> DemoSource:
        if self.content_origin != "public_summary":
            return self
        required = {
            "source_url": self.source_url,
            "source_publisher": self.source_publisher,
            "source_retrieved_at": self.source_retrieved_at,
            "source_usage_note": self.source_usage_note,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "public_summary requires provenance fields: " + ", ".join(missing)
            )
        parsed_url = urlsplit(self.source_url)
        if not parsed_url.netloc or not parsed_url.hostname:
            raise ValueError("source_url must be a valid HTTP(S) URL")
        try:
            _HTTP_URL_VALIDATOR.validate_python(self.source_url)
        except ValidationError as exc:
            raise ValueError("source_url must be a valid HTTP(S) URL") from exc
        return self


class DemoKnowledgeBase(_ImmutableModel):
    key: StableKey
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: str | None = None
    document_keys: tuple[StableKey, ...]


class DemoEvaluationCase(_ImmutableModel):
    key: StableKey
    question: Annotated[str, Field(min_length=1)]
    category: Annotated[str, Field(min_length=1, max_length=100)]
    difficulty: Annotated[str, Field(min_length=1, max_length=50)]
    expected_points: Annotated[
        tuple[Annotated[str, Field(min_length=1)], ...], Field(min_length=1)
    ]
    expected_document_keys: tuple[StableKey, ...]
    should_refuse: bool
    reference_answer: str | None = None


class DemoEvaluationDataset(_ImmutableModel):
    key: StableKey
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: str | None = None
    cases_path: Path

    @field_validator("cases_path", mode="before")
    @classmethod
    def validate_cases_path(cls, value: object) -> Path:
        return _validate_relative_path(value, "cases_path")


class _DemoManifest(_ImmutableModel):
    account: DemoAccount
    knowledge_bases: tuple[DemoKnowledgeBase, ...]
    documents: tuple[DemoSource, ...]
    evaluation_dataset: DemoEvaluationDataset


class _DemoEvaluationFile(_ImmutableModel):
    cases: tuple[DemoEvaluationCase, ...]


class DemoCatalog(_ImmutableModel):
    root: Path
    account: DemoAccount
    knowledge_bases: tuple[DemoKnowledgeBase, ...]
    documents: tuple[DemoSource, ...]
    evaluation_dataset: DemoEvaluationDataset
    evaluation_cases: tuple[DemoEvaluationCase, ...]


def _read_json(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DemoCatalogError(f"cannot read {label} at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DemoCatalogError(f"invalid JSON in {label} at {path}: {exc}") from exc


def _require_unique_keys(items: tuple[object, ...], *, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        key = getattr(item, "key")
        if key in seen:
            raise DemoCatalogError(f"duplicate {label} key: {key}")
        seen.add(key)


def _resolve_local_file(root: Path, relative_path: Path, *, field_name: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DemoCatalogError(
            f"{field_name} escapes demo catalog root: {relative_path}"
        ) from exc
    if not candidate.is_file():
        raise DemoCatalogError(f"{field_name} does not reference a local file: {relative_path}")
    return candidate


def _validate_document_references(
    knowledge_bases: tuple[DemoKnowledgeBase, ...],
    cases: tuple[DemoEvaluationCase, ...],
    document_keys: set[str],
) -> None:
    for knowledge_base in knowledge_bases:
        for document_key in knowledge_base.document_keys:
            if document_key not in document_keys:
                raise DemoCatalogError(
                    f"knowledge base {knowledge_base.key} references unknown "
                    f"document key: {document_key}"
                )
    for case in cases:
        for document_key in case.expected_document_keys:
            if document_key not in document_keys:
                raise DemoCatalogError(
                    f"evaluation case {case.key} references unknown "
                    f"document key: {document_key}"
                )


def load_demo_catalog(root: Path) -> DemoCatalog:
    """Load and validate the demo catalog using local files only."""

    resolved_root = Path(root).resolve()
    manifest_path = resolved_root / "catalog.json"
    try:
        manifest = _DemoManifest.model_validate(
            _read_json(manifest_path, label="demo manifest")
        )
    except ValidationError as exc:
        raise DemoCatalogError(f"invalid demo manifest: {exc}") from exc

    _require_unique_keys(manifest.documents, label="document")
    _require_unique_keys(manifest.knowledge_bases, label="knowledge base")
    for source in manifest.documents:
        _resolve_local_file(
            resolved_root, source.local_path, field_name="local_path"
        )

    cases_path = _resolve_local_file(
        resolved_root,
        manifest.evaluation_dataset.cases_path,
        field_name="cases_path",
    )
    try:
        evaluation_file = _DemoEvaluationFile.model_validate(
            _read_json(cases_path, label="demo evaluation cases")
        )
    except ValidationError as exc:
        raise DemoCatalogError(f"invalid demo evaluation cases: {exc}") from exc

    _require_unique_keys(evaluation_file.cases, label="evaluation case")
    _validate_document_references(
        manifest.knowledge_bases,
        evaluation_file.cases,
        {source.key for source in manifest.documents},
    )

    return DemoCatalog(
        root=resolved_root,
        account=manifest.account,
        knowledge_bases=manifest.knowledge_bases,
        documents=manifest.documents,
        evaluation_dataset=manifest.evaluation_dataset,
        evaluation_cases=evaluation_file.cases,
    )
