from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.modules.rag.trace_models import RagTraceNode, RagTraceRun


@dataclass(slots=True)
class TraceExecution:
    run: RagTraceRun
    started_at: float = field(default_factory=time.perf_counter)


class RagTraceService:
    def start(
        self,
        db: Session,
        *,
        user_id: int,
        query: str,
        request_id: str | None = None,
    ) -> TraceExecution:
        run = RagTraceRun(
            id=uuid.uuid4().hex,
            user_id=user_id,
            query=query,
            request_id=request_id,
        )
        db.add(run)
        db.commit()
        return TraceExecution(run)

    @contextmanager
    def node(self, db: Session, execution: TraceExecution, name: str):
        started_at = time.perf_counter()
        # 节点相对 trace.start 的偏移（Waterfall 真实时序的依据）
        start_offset_ms = (started_at - execution.started_at) * 1000
        attributes: dict[str, Any] = {}
        status = "running"
        try:
            yield attributes
            status = "success"
        except BaseException as exc:
            status = (
                "cancelled"
                if isinstance(exc, (GeneratorExit, asyncio.CancelledError))
                else "failed"
            )
            attributes["error"] = str(exc)
            raise
        finally:
            db.add(
                RagTraceNode(
                    run_id=execution.run.id,
                    name=name,
                    status=status,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    start_offset_ms=round(start_offset_ms, 2),
                    attributes_json=json.dumps(attributes, ensure_ascii=False),
                )
            )
            db.commit()

    def finish(
        self,
        db: Session,
        execution: TraceExecution,
        *,
        conversation_id: str | None,
        rewritten_query: str,
        turn_id: int | None = None,
        error: str | None = None,
        status: str | None = None,
    ) -> None:
        execution.run.conversation_id = conversation_id
        execution.run.rewritten_query = rewritten_query
        execution.run.turn_id = turn_id
        execution.run.status = status or ("failed" if error else "success")
        execution.run.error_message = error
        execution.run.elapsed_ms = round((time.perf_counter() - execution.started_at) * 1000, 2)
        db.commit()
