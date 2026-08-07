from __future__ import annotations

from typing import Protocol

from app.modules.retrieval.models import RetrievalRequest, SearchResult


class SearchChannel(Protocol):
    name: str
    weight: float
    enabled: bool

    async def search(self, request: RetrievalRequest) -> list[SearchResult]: ...


class BaseSearchChannel:
    name = "base"

    def __init__(self, *, weight: float = 1.0, enabled: bool = True):
        self.weight = weight
        self.enabled = enabled
