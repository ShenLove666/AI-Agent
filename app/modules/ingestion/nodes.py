from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.ingestion.models import IngestionContext, NodeResult


Condition = Callable[[IngestionContext], bool]


class IngestionNode(ABC):
    def __init__(self, name: str, condition: Condition | None = None):
        self.name = name
        self.condition = condition

    def should_run(self, context: IngestionContext) -> bool:
        return self.condition(context) if self.condition else True

    @abstractmethod
    async def execute(self, context: IngestionContext) -> NodeResult: ...


class CallableNode(IngestionNode):
    def __init__(
        self,
        name: str,
        handler: Callable[[IngestionContext], Awaitable[Any]],
        condition: Condition | None = None,
    ):
        super().__init__(name, condition)
        self.handler = handler

    async def execute(self, context: IngestionContext) -> NodeResult:
        output = await self.handler(context)
        return output if isinstance(output, NodeResult) else NodeResult(output=output)


class FetcherNode(CallableNode):
    pass

class ParserNode(CallableNode):
    pass


class ChunkerNode(CallableNode):
    pass


class EnhancerNode(CallableNode):
    pass


class EnricherNode(CallableNode):
    pass


class IndexerNode(CallableNode):
    pass
