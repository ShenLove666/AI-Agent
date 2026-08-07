from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class VectorRecord:
    id: str
    vector: Sequence[float]
    content: str
    owner_id: int
    knowledge_base_id: int
    document_id: int
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VectorMatch:
    record: VectorRecord
    score: float


class VectorStore(Protocol):
    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    async def search(
        self,
        vector: Sequence[float],
        *,
        owner_id: int,
        knowledge_base_ids: Sequence[int] = (),
        limit: int = 20,
    ) -> list[VectorMatch]: ...

    async def delete_document(self, document_id: int) -> None: ...
