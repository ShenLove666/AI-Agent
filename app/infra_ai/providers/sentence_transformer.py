from __future__ import annotations

import asyncio
from collections.abc import Sequence


class SentenceTransformerEmbeddingModel:
    """Lazy local embedding provider; importing the app does not load torch."""

    def __init__(self, model_path: str, device: str = "cpu", normalize: bool = True):
        self.name = model_path
        self.model_path = model_path
        self.device = device
        self.normalize = normalize
        self._model = None
        self.dimension = 0
        self._load_lock = asyncio.Lock()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = await asyncio.to_thread(
                    SentenceTransformer, self.model_path, device=self.device
                )
                self.dimension = int(self._model.get_sentence_embedding_dimension())
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        model = await self._ensure_model()
        vectors = await asyncio.to_thread(
            model.encode,
            list(texts),
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
        )
        return vectors.astype(float).tolist()

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]
