from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from app.modules.retrieval.channels import SearchChannel
from app.modules.retrieval.models import ChannelOutcome, RetrievalRequest, RetrievalResponse
from app.modules.retrieval.postprocessors import SearchResultPostProcessor
from app.framework.errors import RetrievalError


class MultiChannelRetrievalEngine:
    def __init__(
        self,
        channels: Sequence[SearchChannel],
        postprocessors: Sequence[SearchResultPostProcessor],
        timeout_seconds: float = 8,
    ):
        self.channels = tuple(channel for channel in channels if channel.enabled)
        self.postprocessors = tuple(postprocessors)
        self.timeout_seconds = timeout_seconds

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        started_at = time.perf_counter()

        async def run_channel(channel: SearchChannel) -> ChannelOutcome:
            channel_started_at = time.perf_counter()
            try:
                results = await asyncio.wait_for(
                    channel.search(request), timeout=self.timeout_seconds
                )
                return ChannelOutcome(
                    channel=channel.name,
                    results=results[: request.candidate_limit],
                    elapsed_ms=round((time.perf_counter() - channel_started_at) * 1000, 2),
                )
            except Exception as exc:
                return ChannelOutcome(
                    channel=channel.name,
                    results=[],
                    elapsed_ms=round((time.perf_counter() - channel_started_at) * 1000, 2),
                    error=str(exc),
                )

        outcomes = list(await asyncio.gather(*(run_channel(channel) for channel in self.channels)))
        if outcomes and all(outcome.error for outcome in outcomes):
            raise RetrievalError(
                "知识检索服务暂时不可用，请稍后重试",
                {
                    "channels": [
                        {"name": outcome.channel, "error": outcome.error}
                        for outcome in outcomes
                    ]
                },
            )
        result_sets = [outcome.results for outcome in outcomes if not outcome.error]

        current_sets = result_sets
        for processor in self.postprocessors:
            processed = await processor.process(request, current_sets)
            current_sets = [processed]

        results = list(current_sets[0] if current_sets else [])[: request.context_limit]
        return RetrievalResponse(
            results=results,
            outcomes=outcomes,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
