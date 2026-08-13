"""共享最终回答生成层：Chat 与 Eval 走同一条「证据 → Prompt → 模型 → 最终回答」。

评审要求：Eval 评的是用户真正看到的最终答案，而不是 Agent 内部拼接的
AgenticRun.answer。这里集中构造 grounded 回答的 prompt 并执行模型流式生成；
model_router 为 None（测试/离线/未配置）时确定性回退为与 AgenticRun.answer
同语义的拼接文案，保证两处口径一致。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable

from app.infra_ai.contracts import (
    ChatMessage,
    ChatRequest as ModelChatRequest,
    ModelStreamChunk,
)


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    content: str
    citations: list[dict[str, Any]]
    first_token_ms: int | None
    thinking_ms: int | None
    runtime_mode: str  # model | fallback


SYSTEM_PROMPT = (
    "你是零售运营 Agent。依据 ReAct 工具返回的资料回答，并区分"
    " observed/derived/synthetic；资料不足时明确说明，不得编造"
    "来源、销量、价格或政策。"
)


class GroundedAnswerRuntime:
    """无状态共享运行时：build_grounded_request 构造 prompt，generate 执行生成。"""

    @staticmethod
    def build_grounded_request(
        *,
        question: str,
        evidence: Iterable[Any],
        history: Iterable[ChatMessage] = (),
        deep_thinking: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelChatRequest:
        documents = list(evidence)
        context = "\n\n".join(
            f"[资料 {index}] {item.content}"
            for index, item in enumerate(documents, start=1)
        )
        user_content = (
            f"用户问题：{question}\n\n可用资料：\n{context}" if context else question
        )
        messages = [ChatMessage("system", SYSTEM_PROMPT)]
        messages.extend(history)
        messages.append(ChatMessage("user", user_content))
        return ModelChatRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata={
                "deep_thinking": deep_thinking,
                "requested_mode": "thinking" if deep_thinking else "normal",
            },
        )

    @staticmethod
    def fallback_answer(evidence: Iterable[Any]) -> str:
        """无模型时的确定性回退（与 AgenticRun.answer 同语义）。"""
        results = list(evidence)
        if not results:
            return "当前证据不足，无法给出可靠结论，建议转人工复核。"
        excerpts = [" ".join(item.content.split())[:240] for item in results[:3]]
        return "根据已检索到的来源证据：" + "；".join(excerpts)

    @classmethod
    async def generate(
        cls,
        model_router,
        *,
        question: str,
        evidence: Iterable[Any],
        history: Iterable[ChatMessage] = (),
        deep_thinking: bool = False,
        cancel_event=None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> GeneratedAnswer:
        """生成最终用户回答。model_router 为 None → 确定性回退（不调用模型）。"""
        if model_router is None:
            return GeneratedAnswer(
                cls.fallback_answer(evidence), [], None, None, "fallback"
            )
        request = cls.build_grounded_request(
            question=question,
            evidence=evidence,
            history=history,
            deep_thinking=deep_thinking,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        started = time.perf_counter()
        first_token_at: float | None = None
        thinking_started_at: float | None = None
        thinking_finished_at: float | None = None
        parts: list[str] = []
        async for chunk in model_router.stream(request, cancel_event=cancel_event):
            if isinstance(chunk, ModelStreamChunk) and chunk.kind == "thinking":
                if thinking_started_at is None:
                    thinking_started_at = time.perf_counter()
                continue
            token = chunk.content if isinstance(chunk, ModelStreamChunk) else chunk
            if first_token_at is None:
                first_token_at = time.perf_counter()
                thinking_finished_at = first_token_at
            parts.append(token)
        thinking_ms = (
            round((thinking_finished_at - thinking_started_at) * 1000)
            if thinking_started_at is not None and thinking_finished_at is not None
            else None
        )
        citations = [
            {"id": item.id, "source": item.source, "content": item.content}
            for item in evidence
        ]
        return GeneratedAnswer(
            "".join(parts),
            citations,
            round((first_token_at - started) * 1000)
            if first_token_at is not None
            else None,
            thinking_ms,
            "model",
        )
