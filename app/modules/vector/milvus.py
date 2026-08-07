from __future__ import annotations

import asyncio
from collections.abc import Sequence

from app.modules.vector.contracts import VectorMatch, VectorRecord


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        dimension: int,
        collection_name: str = "ragent_chunks_v2",
        token: str | None = None,
    ):
        self.uri = uri
        self.dimension = dimension
        self.collection_name = collection_name
        self.token = token
        self._client = None
        self._init_lock = asyncio.Lock()

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        async with self._init_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._create_client)
        return self._client

    def _create_client(self):
        from pymilvus import DataType, MilvusClient

        kwargs = {"uri": self.uri}
        if self.token:
            kwargs["token"] = self.token
        client = MilvusClient(**kwargs)
        if not client.has_collection(self.collection_name):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
            schema.add_field("owner_id", DataType.INT64)
            schema.add_field("knowledge_base_id", DataType.INT64)
            schema.add_field("document_id", DataType.INT64)
            schema.add_field("content", DataType.VARCHAR, max_length=65535)
            schema.add_field("source", DataType.VARCHAR, max_length=1024)
            indexes = MilvusClient.prepare_index_params()
            indexes.add_index(
                field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
            )
            client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=indexes,
            )
        return client

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        client = await self._ensure_client()
        data = [
            {
                "id": record.id,
                "vector": list(record.vector),
                "owner_id": record.owner_id,
                "knowledge_base_id": record.knowledge_base_id,
                "document_id": record.document_id,
                "content": record.content,
                "source": record.source,
                **record.metadata,
            }
            for record in records
        ]
        await asyncio.to_thread(client.upsert, self.collection_name, data=data)

    async def search(
        self,
        vector: Sequence[float],
        *,
        owner_id: int,
        knowledge_base_ids: Sequence[int] = (),
        limit: int = 20,
    ) -> list[VectorMatch]:
        client = await self._ensure_client()
        expression = f"owner_id == {int(owner_id)}"
        if knowledge_base_ids:
            values = ",".join(str(int(item)) for item in knowledge_base_ids)
            expression += f" and knowledge_base_id in [{values}]"
        response = await asyncio.to_thread(
            client.search,
            collection_name=self.collection_name,
            data=[list(vector)],
            filter=expression,
            limit=limit,
            output_fields=[
                "owner_id",
                "knowledge_base_id",
                "document_id",
                "content",
                "source",
                "position",
                "chunk_id",
            ],
        )
        matches: list[VectorMatch] = []
        for hit in response[0]:
            entity = hit.get("entity", {})
            record = VectorRecord(
                id=str(hit["id"]),
                vector=(),
                content=entity.get("content", ""),
                owner_id=int(entity["owner_id"]),
                knowledge_base_id=int(entity["knowledge_base_id"]),
                document_id=int(entity["document_id"]),
                source=entity.get("source", ""),
                metadata={
                    "position": entity.get("position"),
                    "chunk_id": entity.get("chunk_id", str(hit["id"])),
                },
            )
            matches.append(VectorMatch(record=record, score=float(hit["distance"])))
        return matches

    async def delete_document(self, document_id: int) -> None:
        client = await self._ensure_client()
        await asyncio.to_thread(
            client.delete,
            collection_name=self.collection_name,
            filter=f"document_id == {int(document_id)}",
        )
