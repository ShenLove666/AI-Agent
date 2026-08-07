from __future__ import annotations

from typing import AsyncIterator

from openai import AsyncOpenAI

from app.infra_ai.contracts import ChatRequest, ModelStreamChunk


class OpenAICompatibleChatModel:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        reasoning_model: str | None = None,
    ):
        self.name = name
        self.model = model
        self.reasoning_model = reasoning_model
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def _reasoning_enabled(self, request: ChatRequest) -> bool:
        return bool(request.metadata.get("deep_thinking"))

    def _selected_model(self, request: ChatRequest) -> str:
        if self._reasoning_enabled(request) and self.reasoning_model:
            return self.reasoning_model
        return self.model

    def _extra_body(self, request: ChatRequest) -> dict:
        # MiMo v2.5 默认先生成 reasoning_content。当前 RAGent 对话页只消费
        # answer token，因此关闭 thinking，避免思考期间界面一直停在三个点。
        if self.name == "mimo":
            return {
                "thinking": {
                    "type": "enabled" if self._reasoning_enabled(request) else "disabled"
                }
            }
        return {}

    async def complete(self, request: ChatRequest) -> str:
        response = await self.client.chat.completions.create(
            model=self._selected_model(request),
            messages=[{"role": item.role, "content": item.content} for item in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            extra_body=self._extra_body(request),
        )
        return response.choices[0].message.content or ""

    async def stream(self, request: ChatRequest) -> AsyncIterator[str | ModelStreamChunk]:
        response = await self.client.chat.completions.create(
            model=self._selected_model(request),
            messages=[{"role": item.role, "content": item.content} for item in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
            extra_body=self._extra_body(request),
        )
        async for event in response:
            delta = event.choices[0].delta if event.choices else None
            reasoning = getattr(delta, "reasoning_content", None) if delta else None
            if reasoning:
                yield ModelStreamChunk("thinking", reasoning)
            content = delta.content if delta else None
            if content:
                yield ModelStreamChunk("response", content)
