from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def current_trace_id() -> str:
    trace_id = trace_id_var.get()
    if trace_id is None:
        trace_id = uuid.uuid4().hex
        trace_id_var.set(trace_id)
    return trace_id


@dataclass(slots=True)
class TraceNode:
    name: str
    started_at: float = field(default_factory=time.perf_counter)
    elapsed_ms: float | None = None
    status: str = "running"
    attributes: dict[str, Any] = field(default_factory=dict)

    def finish(self, status: str = "success", **attributes: Any) -> None:
        self.elapsed_ms = round((time.perf_counter() - self.started_at) * 1000, 2)
        self.status = status
        self.attributes.update(attributes)
