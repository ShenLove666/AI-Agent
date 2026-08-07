from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IngestionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class NodeLog:
    node: str
    status: IngestionStatus
    elapsed_ms: float
    message: str | None = None


@dataclass(slots=True)
class IngestionContext:
    source: str
    knowledge_base_id: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    payload: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    logs: list[NodeLog] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)


@dataclass(frozen=True, slots=True)
class NodeResult:
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IngestionResult:
    task_id: str
    status: IngestionStatus
    outputs: dict[str, Any]
    logs: list[NodeLog]
    error: str | None = None
