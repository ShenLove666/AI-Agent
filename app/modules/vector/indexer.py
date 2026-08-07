from __future__ import annotations

from collections.abc import Sequence

from app.infra_ai.contracts import EmbeddingModel
from app.modules.vector.contracts import VectorRecord, VectorStore


class VectorIndexer:
    def __init__(self, embeddings: EmbeddingModel, store: VectorStore):
        self.embeddings = embeddings
        self.store = store

    async def index(
        self,
        *,
        owner_id: int,
        knowledge_base_id: int,
        document_id: int,
        source: str,
        chunks: Sequence[tuple[int, int, str]],
    ) -> None:
        """Index chunks using the database primary key as the cross-channel identity."""
        texts = [content for _, _, content in chunks]
        vectors = await self.embeddings.embed_documents(texts)
        await self.store.upsert(
            [
                VectorRecord(
                    id=str(chunk_id),
                    vector=vector,
                    content=content,
                    owner_id=owner_id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    source=source,
                    metadata={"position": position, "chunk_id": chunk_id},
                )
                for (chunk_id, position, content), vector in zip(chunks, vectors)
            ]
        )
