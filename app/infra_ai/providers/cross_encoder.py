from __future__ import annotations

import asyncio
from collections.abc import Sequence


class CrossEncoderRerankModel:
    """Lazy sentence-transformers CrossEncoder reranker."""

    def __init__(self, model_path: str, device: str = "cpu"):
        self.name = model_path
        self.model_path = model_path
        self.device = device
        self._model = None
        self._load_lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = await asyncio.to_thread(
                    CrossEncoder, self.model_path, device=self.device
                )
        return self._model

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        model = await self._ensure_model()
        pairs = [(query, document) for document in documents]
        scores = await asyncio.to_thread(model.predict, pairs)
        return [float(score) for score in scores]
