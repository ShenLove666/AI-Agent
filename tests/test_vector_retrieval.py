from __future__ import annotations

import asyncio

from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest
from app.modules.retrieval.postprocessors import RerankPostProcessor, WeightedRrfPostProcessor
from app.modules.retrieval.vector_channel import VectorSearchChannel
from app.modules.vector.indexer import VectorIndexer
from app.modules.vector.memory import InMemoryVectorStore


class FakeEmbeddings:
    name = "fake"
    dimension = 2

    async def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    async def embed_query(self, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        return [1.0, 0.0] if "报关" in text else [0.0, 1.0]


def test_vector_index_search_and_tenant_isolation():
    async def scenario():
        embeddings = FakeEmbeddings()
        store = InMemoryVectorStore()
        indexer = VectorIndexer(embeddings, store)
        await indexer.index(
            owner_id=1,
            knowledge_base_id=10,
            document_id=100,
            source="customs.txt",
            chunks=[(501, 0, "报关流程包括申报和查验"), (502, 1, "信用证付款流程")],
        )
        await indexer.index(
            owner_id=1,
            knowledge_base_id=20,
            document_id=200,
            source="other.txt",
            chunks=[(601, 0, "报关但属于另一个知识库")],
        )
        channel = VectorSearchChannel(embeddings, store)
        engine = MultiChannelRetrievalEngine(
            [channel], [WeightedRrfPostProcessor({"vector": 1.0})]
        )
        owned = await engine.retrieve(RetrievalRequest("报关", metadata={"user_id": 1}))
        isolated = await engine.retrieve(RetrievalRequest("报关", metadata={"user_id": 2}))
        scoped = await engine.retrieve(
            RetrievalRequest(
                "报关",
                knowledge_base_ids=("10",),
                metadata={"user_id": 1},
            )
        )
        assert owned.results[0].source == "customs.txt"
        assert "报关" in owned.results[0].content
        assert owned.results[0].metadata["chunk_id"] == 501
        assert not isolated.results
        assert scoped.results
        assert {item.metadata["knowledge_base_id"] for item in scoped.results} == {10}

    asyncio.run(scenario())


def test_hybrid_rrf_fuses_the_same_database_chunk_once():
    from app.modules.retrieval.models import SearchResult

    async def scenario():
        processor = WeightedRrfPostProcessor({"keyword": 1.0, "vector": 1.2})
        keyword = SearchResult(
            id="501",
            content="报关流程包括申报和查验",
            score=0.8,
            channel="keyword",
            metadata={"chunk_id": 501},
        )
        vector = SearchResult(
            id="501",
            content="报关流程包括申报和查验",
            score=0.95,
            channel="vector",
            metadata={"chunk_id": 501},
        )

        fused = await processor.process(RetrievalRequest("报关"), [[keyword], [vector]])

        assert len(fused) == 1
        assert [item["channel"] for item in fused[0].metadata["channel_attribution"]] == [
            "keyword",
            "vector",
        ]

    asyncio.run(scenario())


def test_rerank_failure_and_invalid_score_count_fall_back_to_rrf_order():
    from app.modules.retrieval.models import SearchResult

    class BrokenReranker:
        def __init__(self, scores=None):
            self.scores = scores

        async def rerank(self, query, documents):
            if self.scores is None:
                raise RuntimeError("reranker unavailable")
            return self.scores

    async def scenario():
        candidates = [
            SearchResult("1", "first", 0.2, "keyword"),
            SearchResult("2", "second", 0.1, "vector"),
        ]
        for model in (BrokenReranker(), BrokenReranker([0.9])):
            result = await RerankPostProcessor(model).process(
                RetrievalRequest("query"), [candidates]
            )
            assert [item.id for item in result] == ["1", "2"]
            assert all(item.metadata["rerank_degraded"] for item in result)

    asyncio.run(scenario())


def test_all_retrieval_channels_failed_is_not_reported_as_no_hits():
    from app.framework.errors import RetrievalError

    class BrokenChannel:
        name = "broken"
        enabled = True

        async def search(self, request):
            raise RuntimeError("backend down")

    async def scenario():
        engine = MultiChannelRetrievalEngine([BrokenChannel()], [])
        try:
            await engine.retrieve(RetrievalRequest("query"))
        except RetrievalError as exc:
            assert exc.code == "RETRIEVAL_FAILED"
            assert exc.details["channels"][0]["name"] == "broken"
        else:
            raise AssertionError("all-channel failure must be surfaced")

    asyncio.run(scenario())
