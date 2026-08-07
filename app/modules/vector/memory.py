from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence

from app.modules.vector.contracts import VectorMatch, VectorRecord


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryVectorStore:
    """Development/test adapter. Production uses the same interface with Milvus or pgvector."""

    def __init__(self):
        self._records: dict[str, VectorRecord] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        async with self._lock:
            self._records.update({record.id: record for record in records})

    async def search(
        self,
        vector: Sequence[float],
        *,
        owner_id: int,
        knowledge_base_ids: Sequence[int] = (),
        limit: int = 20,
    ) -> list[VectorMatch]:
        allowed_bases = set(knowledge_base_ids)
        matches = [
            VectorMatch(record, cosine_similarity(vector, record.vector))
            for record in self._records.values()
            if record.owner_id == owner_id
            and (not allowed_bases or record.knowledge_base_id in allowed_bases)
        ]
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]

    async def delete_document(self, document_id: int) -> None:
        async with self._lock:
            self._records = {
                key: record
                for key, record in self._records.items()
                if record.document_id != document_id
            }
