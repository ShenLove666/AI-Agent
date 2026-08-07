from __future__ import annotations

import time
from collections.abc import Sequence

from app.modules.ingestion.models import (
    IngestionContext,
    IngestionResult,
    IngestionStatus,
    NodeLog,
)
from app.modules.ingestion.nodes import IngestionNode


class IngestionPipeline:
    """Sequential node pipeline with conditional execution and node-level observability."""

    def __init__(self, name: str, nodes: Sequence[IngestionNode]):
        self.name = name
        self.nodes = tuple(nodes)

    async def execute(self, context: IngestionContext) -> IngestionResult:
        try:
            for node in self.nodes:
                if not node.should_run(context):
                    context.logs.append(NodeLog(node.name, IngestionStatus.SUCCEEDED, 0, "skipped"))
                    continue
                started_at = time.perf_counter()
                try:
                    result = await node.execute(context)
                    context.outputs[node.name] = result.output
                    if result.metadata:
                        context.payload.update(result.metadata)
                    context.logs.append(
                        NodeLog(
                            node.name,
                            IngestionStatus.SUCCEEDED,
                            round((time.perf_counter() - started_at) * 1000, 2),
                        )
                    )
                except Exception as exc:
                    context.logs.append(
                        NodeLog(
                            node.name,
                            IngestionStatus.FAILED,
                            round((time.perf_counter() - started_at) * 1000, 2),
                            str(exc),
                        )
                    )
                    raise
            return IngestionResult(
                task_id=context.task_id,
                status=IngestionStatus.SUCCEEDED,
                outputs=context.outputs,
                logs=context.logs,
            )
        except Exception as exc:
            return IngestionResult(
                task_id=context.task_id,
                status=IngestionStatus.FAILED,
                outputs=context.outputs,
                logs=context.logs,
                error=str(exc),
            )
