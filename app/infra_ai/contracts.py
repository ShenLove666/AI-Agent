from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: Sequence[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = 1024
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelStreamChunk:
    kind: Literal["thinking", "response"]
    content: str


class ChatModel(Protocol):
    name: str

    async def complete(self, request: ChatRequest) -> str: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[str | ModelStreamChunk]: ...


class EmbeddingModel(Protocol):
    name: str
    dimension: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class RerankModel(Protocol):
    name: str

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]: ...
