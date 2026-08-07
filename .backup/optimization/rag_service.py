from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.framework.errors import ProviderUnavailableError
from app.infra_ai.contracts import ChatMessage, ChatRequest as ModelChatRequest
from app.infra_ai.router import ChatModelRouter
from app.modules.conversations.service import ConversationService
from app.modules.rag.rewrite import QueryRewriteService
from app.modules.rag.schemas import ChatRequest, ChatResponse
from app.modules.rag.trace_service import RagTraceService, TraceExecution
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest, SearchResult


@dataclass(slots=True)
class PreparedChat:
    conversation_id: str
    model_request: ModelChatRequest
    citations: list[dict]
    rewritten_query: str
    trace: TraceExecution


class RagChatService:
    def __init__(
        self,
        model_router: ChatModelRouter | None,
        conversations: ConversationService,
        retrieval: MultiChannelRetrievalEngine | None = None,
        rewrite: QueryRewriteService | None = None,
        traces: RagTraceService | None = None,
    ):
        self.model_router = model_router
        self.conversations = conversations
        self.retrieval = retrieval
        self.rewrite = rewrite or QueryRewriteService(model_router)
        self.traces = traces or RagTraceService()

    async def prepare(self, db: Session, user_id: int, request: ChatRequest) -> PreparedChat:
        trace = self.traces.start(db, user_id=user_id, query=request.question)
        conversation = (
            self.conversations.require_owned(db, request.conversation_id, user_id)
            if request.conversation_id
            else self.conversations.create(db, user_id, request.question[:40])
        )
        history = self.conversations.messages(db, conversation.id, user_id)
        self.conversations.add_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            role="user",
            content=request.question,
        )

        with self.traces.node(db, trace, "rewrite") as attributes:
            rewrite = await self.rewrite.rewrite(
                request.question, [(item.role, item.content) for item in history]
            )
            attributes.update(
                rewritten_query=rewrite.rewritten_query,
                fallback=rewrite.used_fallback,
            )

        documents: list[SearchResult] = []
        with self.traces.node(db, trace, "retrieval") as attributes:
            if request.rag_enabled and self.retrieval is not None:
                response = await self.retrieval.retrieve(
                    RetrievalRequest(
                        query=rewrite.rewritten_query,
                        metadata={"user_id": user_id},
                    )
                )
                documents = response.results
                attributes.update(
                    result_count=len(documents),
                    elapsed_ms=response.elapsed_ms,
                    channels=[
                        {
                            "name": outcome.channel,
                            "count": len(outcome.results),
                            "error": outcome.error,
                        }
                        for outcome in response.outcomes
                    ],
                )

        with self.traces.node(db, trace, "prompt") as attributes:
            citations = [
                {
                    "id": item.id,
                    "source": item.source,
                    "score": item.score,
                    "content": item.content,
                    "metadata": item.metadata,
                }
                for item in documents
            ]
            context = "\n\n".join(
                f"[资料 {index}] {item.content}"
                for index, item in enumerate(documents, start=1)
            )
            user_content = request.question
            if context:
                user_content = f"用户问题：{request.question}\n\n可用资料：\n{context}"
            attributes.update(context_count=len(documents), context_chars=len(context))
            model_request = ModelChatRequest(
                messages=[
                    ChatMessage(
                        "system",
                        "你是企业知识库助手。优先依据资料回答；资料不足时明确说明，不得编造来源。",
                    ),
                    ChatMessage("user", user_content),
                ],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        return PreparedChat(
            conversation.id, model_request, citations, rewrite.rewritten_query, trace
        )

    def require_router(self) -> ChatModelRouter:
        if self.model_router is None:
            raise ProviderUnavailableError("尚未配置 LLM API Key")
        return self.model_router

    async def complete(self, db: Session, user_id: int, request: ChatRequest) -> ChatResponse:
        prepared = await self.prepare(db, user_id, request)
        try:
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                answer = await self.require_router().complete(prepared.model_request)
                attributes["answer_chars"] = len(answer)
            self.conversations.add_message(
                db,
                conversation_id=prepared.conversation_id,
                user_id=user_id,
                role="assistant",
                content=answer,
                citations=prepared.citations,
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
            )
            return ChatResponse(
                conversation_id=prepared.conversation_id,
                answer=answer,
                citations=prepared.citations,
                rewritten_query=prepared.rewritten_query,
            )
        except Exception as exc:
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                error=str(exc),
            )
            raise
    async def stream(
        self, db: Session, user_id: int, request: ChatRequest
    ) -> AsyncIterator[dict]:
        prepared = await self.prepare(db, user_id, request)
        yield {"type": "conversation", "data": {"id": prepared.conversation_id}}
        yield {"type": "rewrite", "data": {"query": prepared.rewritten_query}}
        yield {"type": "citations", "data": prepared.citations}
        answer_parts: list[str] = []
        try:
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                async for token in self.require_router().stream(prepared.model_request):
                    answer_parts.append(token)
                    yield {"type": "token", "data": token}
                attributes["answer_chars"] = sum(map(len, answer_parts))
            answer = "".join(answer_parts)
            self.conversations.add_message(
                db,
                conversation_id=prepared.conversation_id,
                user_id=user_id,
                role="assistant",
                content=answer,
                citations=prepared.citations,
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
            )
            yield {"type": "done", "data": {"answer": answer}}
        except Exception as exc:
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                error=str(exc),
            )
            raise
