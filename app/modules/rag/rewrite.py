from __future__ import annotations

from dataclasses import dataclass

from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter
from app.modules.rag.progress import ProgressSink, phase_text
from app.modules.rag.terminal import is_trivial_direct


@dataclass(frozen=True, slots=True)
class RewriteResult:
    original_query: str
    rewritten_query: str
    used_fallback: bool = False
    skip_reason: str | None = None


class QueryRewriteService:
    def __init__(self, router: ChatModelRouter | None):
        self.router = router

    async def rewrite(
        self,
        query: str,
        history: list[tuple[str, str]] | None = None,
        progress: ProgressSink | None = None,
    ) -> RewriteResult:
        # 普通问候/感谢/自我介绍/笑声等：无需改写，直接短路，跳过 LLM 调用。
        # 不发送任何进度事件（trivial direct 的 Timeline 对用户隐藏，steps 为空）。
        if is_trivial_direct(query):
            return RewriteResult(query, query, skip_reason="trivial_direct")

        async def emit_running() -> None:
            if progress is None:
                return
            await progress(
                {
                    "phase": "rewrite",
                    "status": "running",
                    "agent": "rewrite",
                    "title": phase_text("rewrite", "running"),
                    "detail": "正在结合当前对话整理查询信息",
                }
            )

        async def emit_completed(detail: str) -> None:
            if progress is None:
                return
            await progress(
                {
                    "phase": "rewrite",
                    "status": "completed",
                    "agent": "rewrite",
                    "title": phase_text("rewrite", "completed"),
                    "detail": detail,
                }
            )

        await emit_running()
        if not history:
            await emit_completed("已完成问题理解")
            return RewriteResult(query, query, skip_reason="no_history")
        if self.router is None:
            await emit_completed("已使用原问题继续处理")
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
            await emit_completed("已结合上下文整理查询信息")
            return RewriteResult(query, rewritten)
        except Exception:
            await emit_completed("已使用原问题继续处理")
            return RewriteResult(query, query, True)
