from __future__ import annotations

from dataclasses import dataclass

from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter


@dataclass(frozen=True, slots=True)
class RewriteResult:
    original_query: str
    rewritten_query: str
    used_fallback: bool = False
    skip_reason: str | None = None


class QueryRewriteService:
    def __init__(self, router: ChatModelRouter | None):
        self.router = router

    async def rewrite(self, query: str, history: list[tuple[str, str]] | None = None) -> RewriteResult:
        if not history:
            return RewriteResult(query, query, skip_reason="no_history")
        if self.router is None:
            return RewriteResult(query, query, True)
        history_text = "\n".join(f"{role}: {content}" for role, content in (history or [])[-6:])
        request = ChatRequest(
            messages=[
                ChatMessage(
                    "system",
                    "将用户问题改写为适合企业知识库检索的独立查询。补全指代，保留原意，"
                    "不要回答问题，不要扩展用户未询问的内容，只输出改写后的查询。",
                ),
                ChatMessage("user", f"历史对话：\n{history_text}\n\n当前问题：{query}"),
            ],
            temperature=0,
            max_tokens=128,
        )
        try:
            rewritten = (await self.router.complete(request)).strip().strip('"')
            if not rewritten or len(rewritten) > 500:
                raise ValueError("invalid rewrite result")
            return RewriteResult(query, rewritten)
        except Exception:
            return RewriteResult(query, query, True)
