from __future__ import annotations

from collections import defaultdict
from typing import Protocol, Sequence

from app.infra_ai.contracts import RerankModel
from app.modules.retrieval.models import RetrievalRequest, SearchResult


class SearchResultPostProcessor(Protocol):
    async def process(
        self, request: RetrievalRequest, result_sets: Sequence[list[SearchResult]]
    ) -> list[SearchResult]: ...


class DeduplicationPostProcessor:
    async def process(
        self, request: RetrievalRequest, result_sets: Sequence[list[SearchResult]]
    ) -> list[SearchResult]:
        best: dict[str, SearchResult] = {}
        for result in (item for group in result_sets for item in group):
            key = result.deduplication_key()
            current = best.get(key)
            if current is None or result.score > current.score:
                best[key] = result
        return list(best.values())


class WeightedRrfPostProcessor:
    """Weighted reciprocal-rank fusion across independent search channels."""

    def __init__(self, channel_weights: dict[str, float] | None = None, rank_constant: int = 60):
        self.channel_weights = channel_weights or {}
        self.rank_constant = rank_constant

    async def process(
        self, request: RetrievalRequest, result_sets: Sequence[list[SearchResult]]
    ) -> list[SearchResult]:
        fused_scores: defaultdict[str, float] = defaultdict(float)
        representatives: dict[str, SearchResult] = {}
        attributions: defaultdict[str, list[dict]] = defaultdict(list)

        for results in result_sets:
            for rank, result in enumerate(results, start=1):
                key = result.deduplication_key()
                weight = self.channel_weights.get(result.channel, 1.0)
                contribution = weight / (self.rank_constant + rank)
                fused_scores[key] += contribution
                representatives.setdefault(key, result)
                attributions[key].append(
                    {"channel": result.channel, "rank": rank, "score": result.score}
                )

        fused: list[SearchResult] = []
        for key, fused_score in fused_scores.items():
            result = representatives[key]
            result.score = fused_score
            result.metadata["channel_attribution"] = attributions[key]
            fused.append(result)
        return sorted(fused, key=lambda item: item.score, reverse=True)


class RerankPostProcessor:
    def __init__(self, model: RerankModel, candidate_limit: int = 20):
        self.model = model
        self.candidate_limit = candidate_limit

    async def process(
        self, request: RetrievalRequest, result_sets: Sequence[list[SearchResult]]
    ) -> list[SearchResult]:
        candidates = list(result_sets[0] if result_sets else [])[: self.candidate_limit]
        if not candidates:
            return []
        try:
            scores = await self.model.rerank(
                request.query, [item.content for item in candidates]
            )
            if len(scores) != len(candidates):
                raise ValueError(
                    f"reranker returned {len(scores)} scores for {len(candidates)} candidates"
                )
        except Exception as exc:
            for item in candidates:
                item.metadata["rerank_status"] = "failed"
                item.metadata["rerank_degraded"] = True
                item.metadata["rerank_error"] = str(exc)
            return candidates
        for item, score in zip(candidates, scores):
            item.metadata["pre_rerank_score"] = item.score
            item.metadata["rerank_status"] = "success"
            item.metadata["rerank_degraded"] = False
            item.score = float(score)
        return sorted(candidates, key=lambda item: item.score, reverse=True)


class MetadataEnrichmentPostProcessor:
    async def process(
        self, request: RetrievalRequest, result_sets: Sequence[list[SearchResult]]
    ) -> list[SearchResult]:
        results = list(result_sets[0] if result_sets else [])
        for rank, result in enumerate(results, start=1):
            result.metadata["final_rank"] = rank
            result.metadata.setdefault("source", result.source)
        return results
