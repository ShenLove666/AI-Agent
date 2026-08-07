from __future__ import annotations

import asyncio

from app.infra_ai.circuit_breaker import CircuitBreaker, CircuitState
from app.framework.config import Settings
from app.framework.errors import ModelStreamTimeoutError
from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter, RoutedProvider
from app.infra_ai.providers.openai_compatible import OpenAICompatibleChatModel
from app.modules.ingestion.models import IngestionContext, IngestionStatus
from app.modules.ingestion.nodes import CallableNode
from app.modules.ingestion.pipeline import IngestionPipeline
from app.modules.retrieval.channels import BaseSearchChannel
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest, SearchResult
from app.modules.retrieval.postprocessors import WeightedRrfPostProcessor


class FakeChannel(BaseSearchChannel):
    def __init__(self, name: str, results: list[SearchResult], fail: bool = False):
        super().__init__()
        self.name = name
        self.results = results
        self.fail = fail

    async def search(self, request: RetrievalRequest) -> list[SearchResult]:
        if self.fail:
            raise RuntimeError("channel failed")
        return self.results


def test_deepseek_defaults_to_v4_flash_for_chat_and_reasoning(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_REASONING_MODEL", raising=False)

    endpoint = next(
        item for item in Settings().chat_endpoints() if item.name == "deepseek"
    )

    assert endpoint.model == "deepseek-v4-flash"
    assert endpoint.reasoning_model == "deepseek-v4-flash"

    monkeypatch.setenv("DEEPSEEK_MODEL", "custom-chat-model")
    monkeypatch.setenv("DEEPSEEK_REASONING_MODEL", "custom-reasoning-model")

    endpoint = next(
        item for item in Settings().chat_endpoints() if item.name == "deepseek"
    )

    assert endpoint.model == "custom-chat-model"
    assert endpoint.reasoning_model == "custom-reasoning-model"


def test_circuit_breaker_opens_after_threshold():
    async def scenario():
        breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60)
        await breaker.record_failure()
        assert breaker.snapshot().state is CircuitState.CLOSED
        await breaker.record_failure()
        assert breaker.snapshot().state is CircuitState.OPEN
        assert not await breaker.allow_request()

    asyncio.run(scenario())


def test_multi_channel_retrieval_isolates_failure_and_fuses_results():
    async def scenario():
        vector = FakeChannel(
            "vector",
            [
                SearchResult("1", "共享文档", 0.9, "vector", source="a.txt"),
                SearchResult("2", "向量文档", 0.8, "vector"),
            ],
        )
        keyword = FakeChannel(
            "keyword", [SearchResult("1", "共享文档", 10, "keyword", source="a.txt")]
        )
        graph = FakeChannel("graph", [], fail=True)
        engine = MultiChannelRetrievalEngine(
            channels=[vector, keyword, graph],
            postprocessors=[WeightedRrfPostProcessor({"vector": 1.0, "keyword": 1.2})],
        )
        response = await engine.retrieve(RetrievalRequest("报关"))
        assert len(response.results) == 2
        assert response.results[0].content == "共享文档"
        assert len(response.results[0].metadata["channel_attribution"]) == 2
        assert next(item for item in response.outcomes if item.channel == "graph").error

    asyncio.run(scenario())


def test_ingestion_pipeline_passes_node_outputs():
    async def fetch(context: IngestionContext):
        return "raw"

    async def parse(context: IngestionContext):
        return context.outputs["fetch"].upper()

    async def scenario():
        pipeline = IngestionPipeline(
            "default", [CallableNode("fetch", fetch), CallableNode("parse", parse)]
        )
        result = await pipeline.execute(IngestionContext("file.txt", "kb-1"))
        assert result.status is IngestionStatus.SUCCEEDED
        assert result.outputs["parse"] == "RAW"
        assert len(result.logs) == 2

    asyncio.run(scenario())


class HangingChatModel:
    name = "hanging"

    async def complete(self, request: ChatRequest) -> str:
        return ""

    async def stream(self, request: ChatRequest):
        await asyncio.Event().wait()
        yield "never"


def test_stream_router_enforces_first_token_timeout():
    async def scenario():
        router = ChatModelRouter(
            [RoutedProvider(HangingChatModel(), CircuitBreaker(), priority=1)],
            timeout_seconds=1,
            first_token_timeout_seconds=0.02,
            idle_timeout_seconds=0.02,
        )
        request = ChatRequest([ChatMessage("user", "hello")])
        try:
            _ = [chunk async for chunk in router.stream(request)]
        except ModelStreamTimeoutError as exc:
            assert exc.details["stage"] == "first_token"
        else:
            raise AssertionError("stream should time out before the first token")

    asyncio.run(scenario())


def test_stream_router_cancel_interrupts_a_stuck_provider_immediately():
    async def scenario():
        router = ChatModelRouter(
            [RoutedProvider(HangingChatModel(), CircuitBreaker(), priority=1)],
            timeout_seconds=10,
            first_token_timeout_seconds=10,
            idle_timeout_seconds=10,
        )
        cancel_event = asyncio.Event()
        request = ChatRequest([ChatMessage("user", "hello")])

        async def consume():
            return [chunk async for chunk in router.stream(request, cancel_event=cancel_event)]

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        cancel_event.set()
        assert await asyncio.wait_for(task, timeout=0.2) == []

    asyncio.run(scenario())


def test_deep_thinking_selects_reasoning_model_and_provider_flag():
    request = ChatRequest(
        [ChatMessage("user", "分析退款问题")],
        metadata={"deep_thinking": True},
    )
    deepseek = OpenAICompatibleChatModel(
        "deepseek",
        "https://example.invalid/v1",
        "test-key",
        "deepseek-chat",
        reasoning_model="deepseek-reasoner",
    )
    mimo = OpenAICompatibleChatModel(
        "mimo",
        "https://example.invalid/v1",
        "test-key",
        "mimo-chat",
    )

    assert deepseek._selected_model(request) == "deepseek-reasoner"
    assert mimo._extra_body(request) == {"thinking": {"type": "enabled"}}


def test_router_rejects_blank_answer_and_falls_back():
    class BlankModel:
        name = "blank"

        async def complete(self, request: ChatRequest) -> str:
            return "   "

        async def stream(self, request: ChatRequest):
            if False:
                yield ""

    class HealthyModel:
        name = "healthy"

        async def complete(self, request: ChatRequest) -> str:
            return "有效回答"

        async def stream(self, request: ChatRequest):
            yield "有效回答"

    async def scenario():
        router = ChatModelRouter(
            [
                RoutedProvider(BlankModel(), CircuitBreaker(), priority=1),
                RoutedProvider(HealthyModel(), CircuitBreaker(), priority=2),
            ]
        )
        request = ChatRequest([ChatMessage("user", "hello")])
        assert await router.complete(request) == "有效回答"
        assert "".join([chunk async for chunk in router.stream(request)]) == "有效回答"

    asyncio.run(scenario())
