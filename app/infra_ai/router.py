from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from app.framework.errors import ModelStreamTimeoutError, ProviderUnavailableError
from app.infra_ai.circuit_breaker import CircuitBreaker
from app.infra_ai.contracts import ChatModel, ChatRequest, ModelStreamChunk


@dataclass(slots=True)
class RoutedProvider:
    model: ChatModel
    breaker: CircuitBreaker
    priority: int = 100


class ChatModelRouter:
    """Priority failover router with per-provider circuit breakers."""

    def __init__(
        self,
        providers: Sequence[RoutedProvider],
        timeout_seconds: float = 120,
        first_token_timeout_seconds: float = 20,
        idle_timeout_seconds: float = 30,
    ):
        self.providers = tuple(sorted(providers, key=lambda item: item.priority))
        self.timeout_seconds = timeout_seconds
        self.first_token_timeout_seconds = first_token_timeout_seconds
        self.idle_timeout_seconds = idle_timeout_seconds

    async def complete(self, request: ChatRequest) -> str:
        failures: list[dict[str, str]] = []
        for provider in self.providers:
            if not await provider.breaker.allow_request():
                failures.append({"provider": provider.model.name, "reason": "circuit_open"})
                continue
            try:
                result = await asyncio.wait_for(
                    provider.model.complete(request), timeout=self.timeout_seconds
                )
                if not result.strip():
                    raise ValueError("EMPTY_FINAL_ANSWER")
                await provider.breaker.record_success()
                return result
            except Exception as exc:
                await provider.breaker.record_failure()
                failures.append({"provider": provider.model.name, "reason": str(exc)})
        raise ProviderUnavailableError(details={"failures": failures})

    async def stream(
        self,
        request: ChatRequest,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelStreamChunk]:
        failures: list[dict[str, str]] = []
        last_timeout: ModelStreamTimeoutError | None = None
        for provider in self.providers:
            if not await provider.breaker.allow_request():
                continue
            emitted = False
            emitted_answer = False
            try:
                iterator = provider.model.stream(request).__aiter__()
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.timeout_seconds
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise ModelStreamTimeoutError("total", self.timeout_seconds)
                    stage = "idle" if emitted else "first_token"
                    stage_timeout = (
                        self.idle_timeout_seconds if emitted else self.first_token_timeout_seconds
                    )
                    wait_seconds = min(remaining, stage_timeout)
                    next_chunk = asyncio.create_task(anext(iterator))
                    cancel_wait = (
                        asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
                    )
                    waiters = {next_chunk}
                    if cancel_wait is not None:
                        waiters.add(cancel_wait)
                    done, pending = await asyncio.wait(
                        waiters,
                        timeout=wait_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        actual_stage = "total" if remaining <= stage_timeout else stage
                        timeout_value = self.timeout_seconds if actual_stage == "total" else stage_timeout
                        raise ModelStreamTimeoutError(actual_stage, timeout_value)
                    if cancel_wait is not None and cancel_wait in done:
                        next_chunk.cancel()
                        await asyncio.gather(next_chunk, return_exceptions=True)
                        close = getattr(iterator, "aclose", None)
                        if close is not None:
                            await close()
                        return
                    if cancel_wait is not None:
                        cancel_wait.cancel()
                        await asyncio.gather(cancel_wait, return_exceptions=True)
                    try:
                        chunk = next_chunk.result()
                    except StopAsyncIteration:
                        break
                    emitted = True
                    content = chunk.content if isinstance(chunk, ModelStreamChunk) else chunk
                    if (
                        (not isinstance(chunk, ModelStreamChunk) or chunk.kind == "response")
                        and content.strip()
                    ):
                        emitted_answer = True
                    yield chunk
                if not emitted_answer:
                    raise ValueError("EMPTY_FINAL_ANSWER")
                await provider.breaker.record_success()
                return
            except Exception as exc:
                await provider.breaker.record_failure()
                failures.append({"provider": provider.model.name, "reason": str(exc)})
                if isinstance(exc, ModelStreamTimeoutError):
                    last_timeout = exc
                if emitted:
                    raise
        if last_timeout is not None:
            raise last_timeout
        raise ProviderUnavailableError(details={"failures": failures})
