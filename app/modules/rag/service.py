from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.framework.errors import AppError, ProviderUnavailableError
from app.infra_ai.contracts import ChatMessage, ChatRequest as ModelChatRequest, ModelStreamChunk
from app.infra_ai.router import ChatModelRouter
from app.modules.conversations.models import ChatRequestRun, ConversationTurn, Message
from app.modules.conversations.service import ConversationService
from app.modules.rag.prompt_budget import count_tokens, truncate_to_tokens
from app.modules.rag.rewrite import QueryRewriteService, RewriteResult
from app.modules.rag.schemas import ChatRequest, ChatResponse
from app.modules.rag.trace_service import RagTraceService, TraceExecution
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.models import RetrievalRequest, SearchResult


@dataclass(slots=True)
class PreparedChat:
    conversation_id: str
    conversation_title: str
    turn: ConversationTurn
    user_message_id: int
    model_request: ModelChatRequest
    citations: list[dict]
    rewritten_query: str
    trace: TraceExecution
    request_run_id: int | None = None


class RagChatService:
    def __init__(
        self,
        model_router: ChatModelRouter | None,
        conversations: ConversationService,
        retrieval: MultiChannelRetrievalEngine | None = None,
        rewrite: QueryRewriteService | None = None,
        traces: RagTraceService | None = None,
        retrieval_candidate_limit: int = 20,
        retrieval_context_limit: int = 6,
        history_token_budget: int = 3000,
        context_token_budget: int = 4000,
    ):
        self.model_router = model_router
        self.conversations = conversations
        self.retrieval = retrieval
        self.rewrite = rewrite or QueryRewriteService(model_router)
        self.traces = traces or RagTraceService()

        self.retrieval_candidate_limit = retrieval_candidate_limit
        self.retrieval_context_limit = retrieval_context_limit
        self.history_token_budget = history_token_budget
        self.context_token_budget = context_token_budget

    def _budget_history(
        self, history: list[tuple[Message, Message]]
    ) -> list[ChatMessage]:
        selected_turns: list[list[ChatMessage]] = []
        remaining = self.history_token_budget
        for user_message, assistant_message in reversed(history):
            cost = count_tokens(user_message.content) + count_tokens(assistant_message.content)
            if cost > remaining:
                break
            selected_turns.append(
                [
                    ChatMessage("user", user_message.content),
                    ChatMessage("assistant", assistant_message.content),
                ]
            )
            remaining -= cost
        return [item for turn in reversed(selected_turns) for item in turn]

    def _budget_documents(self, documents: list[SearchResult]) -> list[SearchResult]:
        selected: list[SearchResult] = []
        remaining = self.context_token_budget
        for item in documents:
            if remaining <= 0:
                break
            content = truncate_to_tokens(item.content, remaining)
            if not content:
                break
            selected.append(
                SearchResult(
                    id=item.id,
                    content=content,
                    score=item.score,
                    channel=item.channel,
                    source=item.source,
                    metadata=item.metadata,
                )
            )
            remaining -= count_tokens(content)
        return selected

    @staticmethod
    def _fingerprint(
        request: ChatRequest, *, conversation_id: str | None | object = ...
    ) -> str:
        normalized_conversation_id = (
            request.conversation_id if conversation_id is ... else conversation_id
        )
        canonical = json.dumps(
            {
                "conversation_id": normalized_conversation_id,
                "question": request.question,
                "deep_thinking": request.deep_thinking,
                "rag_enabled": request.rag_enabled,
                "knowledge_base_ids": sorted(set(request.knowledge_base_ids)),
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "turn_id": request.turn_id,
                "regenerate": request.regenerate,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _assert_fingerprint(cls, run: ChatRequestRun, request: ChatRequest) -> None:
        fingerprints = {cls._fingerprint(request)}
        if (
            run.requested_conversation_id is None
            and run.conversation_id is not None
            and request.conversation_id == run.conversation_id
        ):
            fingerprints.add(cls._fingerprint(request, conversation_id=None))
        if not run.request_fingerprint or run.request_fingerprint not in fingerprints:
            raise AppError(
                "IDEMPOTENCY_CONFLICT",
                "该 requestId 已用于不同的请求，请生成新的 requestId",
                409,
            )

    @staticmethod
    def _request_run(db: Session, user_id: int, request_id: str) -> ChatRequestRun | None:
        return db.scalar(
            select(ChatRequestRun).where(
                ChatRequestRun.user_id == user_id,
                ChatRequestRun.request_id == request_id,
            )
        )

    def _cached_message(
        self, db: Session, user_id: int, request: ChatRequest
    ) -> tuple[ChatRequestRun, Message] | None:
        if not request.request_id:
            return None
        run = self._request_run(db, user_id, request.request_id)
        if run is not None:
            self._assert_fingerprint(run, request)
        if not run or run.status != "completed" or not run.assistant_message_id:
            return None
        message = db.get(Message, run.assistant_message_id)
        return (
            (run, message)
            if message is not None and message.message_status == "NORMAL"
            else None
        )

    def _begin_request(
        self, db: Session, user_id: int, request: ChatRequest
    ) -> ChatRequestRun | None:
        if not request.request_id:
            return None
        run = self._request_run(db, user_id, request.request_id)
        if run is not None:
            self._assert_fingerprint(run, request)
            stale_before = datetime.utcnow() - timedelta(minutes=5)
            if run.status == "processing" and run.updated_at >= stale_before:
                raise AppError("REQUEST_IN_PROGRESS", "该问题正在生成中，请勿重复提交", 409)
            previous_status = run.status
            previous_updated_at = run.updated_at
            claimed = db.execute(
                update(ChatRequestRun)
                .where(
                    ChatRequestRun.id == run.id,
                    ChatRequestRun.status == previous_status,
                    ChatRequestRun.updated_at == previous_updated_at,
                )
                .values(
                    status="processing",
                    error_message=None,
                    updated_at=datetime.utcnow(),
                )
            )
            if claimed.rowcount != 1:
                db.rollback()
                raise AppError("REQUEST_IN_PROGRESS", "该问题正在生成中，请勿重复提交", 409)
            db.commit()
            db.refresh(run)
            return run
        run = ChatRequestRun(
            user_id=user_id,
            request_id=request.request_id,
            request_fingerprint=self._fingerprint(request),
            requested_conversation_id=request.conversation_id,
            status="processing",
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise AppError("REQUEST_IN_PROGRESS", "该问题正在生成中，请勿重复提交", 409) from exc
        db.refresh(run)
        return run

    @staticmethod
    def _finish_request(
        db: Session,
        request_run_id: int | None,
        *,
        status: str,
        assistant_message_id: int | None = None,
        error: str | None = None,
    ) -> None:
        if request_run_id is None:
            return
        run = db.get(ChatRequestRun, request_run_id)
        if run is None:
            return
        run.status = status
        run.assistant_message_id = assistant_message_id
        run.error_message = error
        db.commit()

    async def prepare(
        self,
        db: Session,
        user_id: int,
        request: ChatRequest,
        trace: TraceExecution,
    ) -> PreparedChat:
        request_run = self._begin_request(db, user_id, request)
        turn = (
            self.conversations.require_owned_turn(db, request.turn_id, user_id)
            if request.turn_id is not None
            else (
                self.conversations.require_owned_turn(db, request_run.turn_id, user_id)
                if request_run is not None and request_run.turn_id is not None
                else None
            )
        )
        conversation = (
            self.conversations.require_owned(
                db,
                request_run.conversation_id
                if request_run and request_run.conversation_id
                else (turn.conversation_id if turn is not None else request.conversation_id),
                user_id,
            )
            if (
                request.conversation_id
                or turn is not None
                or (request_run and request_run.conversation_id)
            )
            else self.conversations.create(db, user_id, request.question[:40])
        )
        if turn is not None and turn.conversation_id != conversation.id:
            raise AppError("TURN_CONVERSATION_MISMATCH", "轮次不属于当前会话", 409)
        if request_run is not None and request_run.conversation_id is None:
            request_run.conversation_id = conversation.id
            db.commit()
        if turn is None:
            turn, user_message = self.conversations.create_turn(
                db,
                conversation_id=conversation.id,
                user_id=user_id,
                question=request.question,
                rag_enabled=request.rag_enabled,
                deep_thinking=request.deep_thinking,
                knowledge_base_ids=request.knowledge_base_ids,
            )
        else:
            user_message = db.get(Message, turn.user_message_id)
            if user_message is None:
                raise AppError("TURN_USER_MESSAGE_MISSING", "轮次缺少用户消息", 409)
            if user_message.content != request.question:
                raise AppError("TURN_QUESTION_MISMATCH", "重生成问题与原轮次不一致", 409)
        if request_run is not None:
            request_run.turn_id = turn.id
            request_run.user_message_id = user_message.id
            db.commit()
        trace.run.conversation_id = conversation.id
        trace.run.turn_id = turn.id
        db.commit()

        history = self.conversations.active_history(
            db,
            conversation.id,
            user_id,
            before_sequence=turn.sequence,
        )
        budgeted_history = self._budget_history(history)

        with self.traces.node(db, trace, "rewrite") as attributes:
            rewrite = (
                await self.rewrite.rewrite(
                    request.question,
                    [(item.role, item.content) for item in budgeted_history],
                )
                if request.rag_enabled
                else RewriteResult(
                    request.question, request.question, skip_reason="rag_disabled"
                )
            )
            attributes.update(
                rewritten_query=rewrite.rewritten_query,
                fallback=rewrite.used_fallback,
                skip_reason=rewrite.skip_reason,
                history_messages=len(budgeted_history),
            )

        documents: list[SearchResult] = []
        with self.traces.node(db, trace, "retrieval") as attributes:
            if request.rag_enabled and self.retrieval is not None:
                response = await self.retrieval.retrieve(
                    RetrievalRequest(
                        query=rewrite.rewritten_query,
                        knowledge_base_ids=tuple(str(item) for item in request.knowledge_base_ids),
                        candidate_limit=self.retrieval_candidate_limit,
                        context_limit=self.retrieval_context_limit,
                        metadata={"user_id": user_id},
                    )
                )
                documents = self._budget_documents(response.results)
                attributes.update(
                    result_count=len(documents),
                    elapsed_ms=response.elapsed_ms,
                    requested_knowledge_base_ids=request.knowledge_base_ids,
                    resolved_knowledge_base_ids=request.knowledge_base_ids,
                    channels=[
                        {
                            "name": outcome.channel,
                            "count": len(outcome.results),
                            "error": outcome.error,
                        }
                        for outcome in response.outcomes
                    ],
                    rerank_degraded=any(
                        item.metadata.get("rerank_degraded", False) for item in documents
                    ),
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
            messages = [
                ChatMessage(
                    "system",
                    "你是企业知识库助手。优先依据资料回答；资料不足时明确说明，不得编造来源。",
                )
            ]
            messages.extend(budgeted_history)
            messages.append(ChatMessage("user", user_content))
            attributes.update(
                context_count=len(documents),
                context_chars=len(context),
                context_tokens=count_tokens(context),
                history_messages_used=len(budgeted_history),
                history_tokens=sum(count_tokens(item.content) for item in budgeted_history),
                prompt_messages=len(messages),
                requested_mode="thinking" if request.deep_thinking else "normal",
                reasoning_enabled=request.deep_thinking,
            )
            model_request = ModelChatRequest(
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                metadata={
                    "deep_thinking": request.deep_thinking,
                    "requested_mode": "thinking" if request.deep_thinking else "normal",
                },
            )
        return PreparedChat(
            conversation.id,
            conversation.title,
            turn,
            user_message.id,
            model_request,
            citations,
            rewrite.rewritten_query,
            trace,
            request_run.id if request_run is not None else None,
        )

    def require_router(self) -> ChatModelRouter:
        if self.model_router is None:
            raise ProviderUnavailableError("尚未配置 LLM API Key")
        return self.model_router

    async def complete(self, db: Session, user_id: int, request: ChatRequest) -> ChatResponse:
        cached = self._cached_message(db, user_id, request)
        if cached is not None:
            run, message = cached
            return ChatResponse(
                conversation_id=run.conversation_id or message.conversation_id,
                answer=message.content,
                citations=json.loads(message.citations_json or "[]"),
                rewritten_query=None,
                turn_id=message.turn_id,
                user_message_id=run.user_message_id,
                assistant_message_id=message.id,
                version=message.version,
            )
        trace = self.traces.start(db, user_id=user_id, query=request.question)
        try:
            prepared = await self.prepare(db, user_id, request, trace)
        except Exception as exc:
            if not isinstance(exc, AppError) or exc.code != "REQUEST_IN_PROGRESS":
                run = self._request_run(db, user_id, request.request_id) if request.request_id else None
                self._finish_request(
                    db, run.id if run else None, status="failed", error=str(exc)
                )
            self.traces.finish(
                db,
                trace,
                conversation_id=trace.run.conversation_id or request.conversation_id,
                rewritten_query=request.question,
                turn_id=trace.run.turn_id,
                error=str(exc),
            )
            raise
        try:
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                answer = await self.require_router().complete(prepared.model_request)
                attributes["answer_chars"] = len(answer)
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=user_id,
                content=answer,
                citations=prepared.citations,
                message_status="NORMAL",
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                turn_id=prepared.turn.id,
            )
            self._finish_request(
                db,
                prepared.request_run_id,
                status="completed",
                assistant_message_id=message.id,
            )
            return ChatResponse(
                conversation_id=prepared.conversation_id,
                answer=answer,
                citations=prepared.citations,
                rewritten_query=prepared.rewritten_query,
                turn_id=prepared.turn.id,
                user_message_id=prepared.user_message_id,
                assistant_message_id=message.id,
                version=message.version,
            )
        except Exception as exc:
            self._finish_request(
                db, prepared.request_run_id, status="failed", error=str(exc)
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                turn_id=prepared.turn.id,
                error=str(exc),
            )
            raise

    async def stream(
        self,
        db: Session,
        user_id: int,
        request: ChatRequest,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict]:
        cached = self._cached_message(db, user_id, request)
        if cached is not None:
            run, message = cached
            citations = json.loads(message.citations_json or "[]")
            yield {
                "type": "conversation",
                "data": {
                    "id": run.conversation_id or message.conversation_id,
                    "turn_id": message.turn_id,
                    "user_message_id": run.user_message_id,
                },
            }
            yield {"type": "rewrite", "data": {"query": request.question}}
            yield {"type": "citations", "data": citations}
            if message.thinking_content:
                yield {"type": "thinking", "data": message.thinking_content}
            if message.content:
                yield {"type": "token", "data": message.content}
            yield {
                "type": "done",
                "data": {
                    "answer": message.content,
                    "message_id": message.id,
                    "turn_id": message.turn_id,
                    "user_message_id": run.user_message_id,
                    "version": message.version,
                },
            }
            return
        trace = self.traces.start(db, user_id=user_id, query=request.question)
        try:
            prepared = await self.prepare(db, user_id, request, trace)
        except Exception as exc:
            if not isinstance(exc, AppError) or exc.code != "REQUEST_IN_PROGRESS":
                run = self._request_run(db, user_id, request.request_id) if request.request_id else None
                self._finish_request(
                    db, run.id if run else None, status="failed", error=str(exc)
                )
            self.traces.finish(
                db,
                trace,
                conversation_id=trace.run.conversation_id or request.conversation_id,
                rewritten_query=request.question,
                turn_id=trace.run.turn_id,
                error=str(exc),
            )
            raise
        yield {
            "type": "conversation",
            "data": {
                "id": prepared.conversation_id,
                "title": prepared.conversation_title,
                "turn_id": prepared.turn.id,
                "user_message_id": prepared.user_message_id,
            },
        }
        yield {"type": "rewrite", "data": {"query": prepared.rewritten_query}}
        yield {"type": "citations", "data": prepared.citations}
        answer_parts: list[str] = []
        thinking_parts: list[str] = []
        try:
            interrupted = False
            generation_started_at = time.perf_counter()
            first_token_at: float | None = None
            thinking_started_at: float | None = None
            thinking_finished_at: float | None = None
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                async for chunk in self.require_router().stream(
                    prepared.model_request, cancel_event=cancel_event
                ):
                    if isinstance(chunk, ModelStreamChunk) and chunk.kind == "thinking":
                        if thinking_started_at is None:
                            thinking_started_at = time.perf_counter()
                        thinking_parts.append(chunk.content)
                        yield {"type": "thinking", "data": chunk.content}
                        continue
                    token = chunk.content if isinstance(chunk, ModelStreamChunk) else chunk
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        thinking_finished_at = first_token_at
                    answer_parts.append(token)
                    yield {"type": "token", "data": token}
                interrupted = bool(cancel_event is not None and cancel_event.is_set())
                attributes.update(
                    answer_chars=sum(map(len, answer_parts)),
                    interrupted=interrupted,
                    ttft_ms=(
                        round((first_token_at - generation_started_at) * 1000, 2)
                        if first_token_at is not None
                        else None
                    ),
                    requested_mode=prepared.model_request.metadata.get("requested_mode"),
                    reasoning_enabled=prepared.model_request.metadata.get("deep_thinking", False),
                    thinking_chars=sum(map(len, thinking_parts)),
                )
            answer = "".join(answer_parts)
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=user_id,
                content=answer,
                citations=prepared.citations,
                message_status="INTERRUPTED" if interrupted else "NORMAL",
                thinking_content="".join(thinking_parts) or None,
                thinking_duration_ms=(
                    round((thinking_finished_at - thinking_started_at) * 1000)
                    if thinking_started_at is not None and thinking_finished_at is not None
                    else None
                ),
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                turn_id=prepared.turn.id,
                status="cancelled" if interrupted else "success",
            )
            self._finish_request(
                db,
                prepared.request_run_id,
                status="cancelled" if interrupted else "completed",
                assistant_message_id=message.id,
            )
            event_type = "cancelled" if interrupted else "done"
            yield {
                "type": event_type,
                "data": {
                    "answer": answer,
                    "message_id": message.id,
                    "turn_id": prepared.turn.id,
                    "user_message_id": prepared.user_message_id,
                    "version": message.version,
                },
            }
        except BaseException as exc:
            answer = "".join(answer_parts)
            cancelled = isinstance(exc, (GeneratorExit, asyncio.CancelledError))
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=user_id,
                content=answer,
                citations=prepared.citations,
                message_status="INTERRUPTED" if cancelled else "ERROR",
                thinking_content="".join(thinking_parts) or None,
                thinking_duration_ms=(
                    round(((thinking_finished_at or time.perf_counter()) - thinking_started_at) * 1000)
                    if thinking_started_at is not None
                    else None
                ),
            )
            self.traces.finish(
                db,
                prepared.trace,
                conversation_id=prepared.conversation_id,
                rewritten_query=prepared.rewritten_query,
                turn_id=prepared.turn.id,
                error=None if cancelled else str(exc),
                status="cancelled" if cancelled else "failed",
            )
            self._finish_request(
                db,
                prepared.request_run_id,
                status="cancelled" if cancelled else "failed",
                assistant_message_id=message.id,
                error=None if cancelled else str(exc),
            )
            if cancelled:
                raise
            yield {
                "type": "error",
                "data": {
                    "message_id": message.id,
                    "turn_id": prepared.turn.id,
                    "user_message_id": prepared.user_message_id,
                    "version": message.version,
                    "code": getattr(exc, "code", "GENERATION_FAILED"),
                    "error": str(exc) if isinstance(exc, AppError) else "生成失败，请稍后重试",
                },
            }
