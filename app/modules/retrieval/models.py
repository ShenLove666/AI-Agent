from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    query: str
    knowledge_base_ids: tuple[str, ...] = ()
    candidate_limit: int = 20
    context_limit: int = 6
    filters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    id: str
    content: str
    score: float
    channel: str
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def deduplication_key(self) -> str:
        explicit = self.metadata.get("chunk_id") or self.metadata.get("document_id")
        if explicit:
            return str(explicit)
        return " ".join(self.content.lower().split())[:500]


@dataclass(slots=True)
class ChannelOutcome:
    channel: str
    results: list[SearchResult]
    elapsed_ms: float
    error: str | None = None


@dataclass(slots=True)
class RetrievalResponse:
    results: list[SearchResult]
    outcomes: list[ChannelOutcome]
    elapsed_ms: float
