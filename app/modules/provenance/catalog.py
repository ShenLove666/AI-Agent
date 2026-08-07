from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from app.modules.provenance.models import PROVENANCE_VALUES


class ProvenanceError(ValueError):
    """Raised before mutation when source metadata or lineage is invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    sha256: str
    rows: int

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "SnapshotFile":
        path = str(value.get("path", ""))
        digest = str(value.get("sha256", ""))
        rows = value.get("rows")
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ProvenanceError("快照文件必须是安全的相对路径")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ProvenanceError("快照 SHA256 无效")
        if not isinstance(rows, int) or rows < 0:
            raise ProvenanceError("快照行数无效")
        return cls(path=path, sha256=digest, rows=rows)


@dataclass(frozen=True)
class DataManifest:
    dataset_key: str
    version: str
    title: str
    source_kind: str
    source_uri: str
    publisher: str
    license: str
    retrieved_at: date
    encoding: str
    transform_version: str
    source_sha256: Mapping[str, str]
    schema: Mapping[str, Any]
    limitations: tuple[str, ...]
    files: tuple[SnapshotFile, ...]
    counts: Mapping[str, int]
    selection_rules: tuple[str, ...]

    @classmethod
    def load(cls, path: Path, *, verify_files: bool = True) -> "DataManifest":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProvenanceError(f"无法读取数据清单：{path}") from exc
        required = ("dataset_key", "version", "title", "source_kind", "source_uri", "publisher", "license", "retrieved_at", "encoding", "transform_version")
        if any(not str(raw.get(key, "")).strip() for key in required):
            raise ProvenanceError("数据清单缺少必填来源字段")
        try:
            retrieved_at = date.fromisoformat(raw["retrieved_at"])
            files = tuple(SnapshotFile.parse(item) for item in raw.get("files", []))
        except (TypeError, ValueError) as exc:
            raise ProvenanceError("数据清单日期或文件定义无效") from exc
        if not files:
            raise ProvenanceError("数据清单没有离线快照")
        counts = raw.get("counts", {})
        if not isinstance(counts, dict) or any(not isinstance(v, int) or v < 0 for v in counts.values()):
            raise ProvenanceError("数据清单统计无效")
        result = cls(
            dataset_key=raw["dataset_key"], version=raw["version"], title=raw["title"],
            source_kind=raw["source_kind"], source_uri=raw["source_uri"], publisher=raw["publisher"],
            license=raw["license"], retrieved_at=retrieved_at, encoding=raw["encoding"],
            transform_version=raw["transform_version"], source_sha256=dict(raw.get("source_sha256", {})),
            schema=dict(raw.get("schema", {})), limitations=tuple(raw.get("limitations", [])),
            files=files, counts=dict(counts), selection_rules=tuple(raw.get("selection_rules", [])),
        )
        if verify_files:
            root = path.parent.resolve()
            for item in files:
                candidate = (root / item.path).resolve()
                if candidate.parent != root or not candidate.is_file() or candidate.is_symlink():
                    raise ProvenanceError(f"快照文件不存在或越界：{item.path}")
                if sha256_bytes(candidate.read_bytes()) != item.sha256:
                    raise ProvenanceError(f"快照校验失败：{item.path}")
        return result

    @property
    def manifest_sha256(self) -> str:
        payload = {
            "dataset_key": self.dataset_key, "version": self.version, "source_uri": self.source_uri,
            "files": [item.__dict__ for item in self.files], "counts": self.counts,
            "transform_version": self.transform_version,
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))


def validate_lineage(lineage: Mapping[str, Any], *, allowed_fields: set[str] | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(lineage, Mapping) or not lineage:
        raise ProvenanceError("字段血缘不能为空")
    normalized: dict[str, dict[str, Any]] = {}
    for field, detail in lineage.items():
        if allowed_fields is not None and field not in allowed_fields:
            raise ProvenanceError(f"未知血缘字段：{field}")
        if not isinstance(detail, Mapping) or detail.get("provenance") not in PROVENANCE_VALUES:
            raise ProvenanceError(f"字段 {field} 的 provenance 无效")
        source_field = detail.get("source_field")
        if detail["provenance"] == "observed" and not source_field:
            raise ProvenanceError(f"观测字段 {field} 必须声明 source_field")
        if detail["provenance"] == "synthetic" and source_field:
            raise ProvenanceError(f"合成字段 {field} 不能冒充源字段")
        normalized[str(field)] = dict(detail)
    return normalized


def assert_same_owner(*owner_ids: int) -> None:
    if not owner_ids or len(set(owner_ids)) != 1:
        raise ProvenanceError("来源与业务记录必须属于同一商家")
