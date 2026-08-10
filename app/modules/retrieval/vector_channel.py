from __future__ import annotations

from app.infra_ai.contracts import EmbeddingModel
from app.modules.retrieval.channels import BaseSearchChannel
from app.modules.retrieval.models import RetrievalRequest, SearchResult
from app.modules.vector.contracts import VectorStore


class VectorSearchChannel(BaseSearchChannel):
    name = "vector"

    def __init__(
        self,
        embeddings: EmbeddingModel,
        store: VectorStore,
        *,
        weight: float = 1.0,
        enabled: bool = True,
    ):
        super().__init__(weight=weight, enabled=enabled)
        self.embeddings = embeddings
        self.store = store

    async def search(self, request: RetrievalRequest) -> list[SearchResult]:
        # owner 过滤统一以 metadata["owner_id"] 优先（业务数据归属），
        # user_id 保留为兼容回退（旧调用方仍只传 user_id）。
        owner_id = int(
            request.metadata.get("owner_id") or request.metadata.get("user_id")
        )
        vector = await self.embeddings.embed_query(request.query)
        matches = await self.store.search(
            vector,
            owner_id=owner_id,
            knowledge_base_ids=[int(item) for item in request.knowledge_base_ids],
            limit=request.candidate_limit,
        )
        return [
            SearchResult(
                id=match.record.id,
                content=match.record.content,
                score=match.score,
                channel=self.name,
                source=match.record.source,
                metadata={
                    **match.record.metadata,
                    "document_id": match.record.document_id,
                    "knowledge_base_id": match.record.knowledge_base_id,
                },
            )
            for match in matches
        ]
