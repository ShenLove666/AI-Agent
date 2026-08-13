from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.framework.errors import AppError, ProviderUnavailableError
from app.infra_ai.contracts import ChatMessage, ChatRequest as ModelChatRequest, ModelStreamChunk
from app.infra_ai.router import ChatModelRouter
from app.modules.conversations.models import (
    ChatRequestRun,
    Conversation,
    ConversationTurn,
    Message,
)
from app.modules.conversations.service import ConversationService
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.rag.prompt_budget import count_tokens, truncate_to_tokens
from app.modules.rag.answer_runtime import GroundedAnswerRuntime
from app.modules.rag.progress import (
    AgentProgressEvent,
    ProgressSink,
    build_execution_summary,
    make_counting_sink,
    phase_text,
)
from app.modules.rag.intent_router import ConversationIntentRouter, IntentDecision
from app.modules.rag.rewrite import QueryRewriteService, RewriteResult
from app.modules.rag.schemas import ChatRequest, ChatResponse
from app.modules.rag.terminal import build_terminal_response
from app.modules.rag.trace_service import RagTraceService, TraceExecution
from app.modules.rag.agentic import AgenticRagCoordinator
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
    # agentic 决策模式（direct/research/refuse/escalate；非 agentic 回退 research）
    agent_mode: str | None = None
    # agentic 终态（direct/grounded/refused/escalated；非 agentic 回退 grounded）。
    # complete()/stream() 生成阶段按它分流：refused/escalated 不调用模型，
    # direct 用普通助手 prompt，grounded 走证据上下文。
    agent_terminal_state: str | None = None
    # 收集的原始 agent 进度事件（prepare 阶段，seq/timestamp 已编号），
    # generation 阶段由 complete()/stream() 继续追加，持久化时再做 reducer 合并。
    agent_execution_events: list[AgentProgressEvent] = field(default_factory=list)
    # 意图前置路由结果（direct/history_reference/research/refuse）。
    # complete()/stream() 生成阶段按它分流（配合 prebuilt_answer），
    # complete 事件携带同值。
    intent: str | None = None
    # 执行模式：direct/history_reference/research/refuse（与 intent 同步，
    # 语义上描述「本条消息走了哪条执行路径」）。
    execution_mode: str | None = None
    # history_reference/refuse 的确定性回答文本（生成阶段直接输出，
    # 不调用模型）；None 表示正常模型生成。
    prebuilt_answer: str | None = None


_TERMINAL_SENTENCE_ENDINGS = "。！？"


def _split_terminal_text(text: str) -> list[str]:
    """把固定终态文案按句子拆分（保留句尾标点），供 SSE 分段输出。

    整段一次输出在浏览器端与普通 token 流的渐进渲染体验不一致，
    按句子拆 2-3 段保持流式呈现；纯文本函数，无副作用。
    """
    parts: list[str] = []
    buffer: list[str] = []
    for char in text:
        buffer.append(char)
        if char in _TERMINAL_SENTENCE_ENDINGS:
            parts.append("".join(buffer))
            buffer = []
    if buffer:
        parts.append("".join(buffer))
    return parts or [text]


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
        agentic: AgenticRagCoordinator | None = None,
        runtime_settings_repository=None,
        intent_router: ConversationIntentRouter | None = None,
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
        self.agentic = agentic
        self.runtime_settings_repository = runtime_settings_repository
        # 意图前置路由（Intent → Rewrite → Research）。构造时创建，测试可注入
        # 自定义实例；model_router 在每次 classify 前同步为服务当前值
        # （运行期/测试会整体替换 router 实例，避免陈旧绑定）。
        self.intent_router = intent_router or ConversationIntentRouter(
            self.model_router
        )

    def _apply_runtime_overrides(self, db: Session) -> None:
        """应用运行时配置中「立即生效」的参数（保存后无需重启）。"""
        if self.runtime_settings_repository is None:
            return
        overrides = self.runtime_settings_repository.get_all(db)
        self.retrieval_candidate_limit = int(
            overrides.get("retrieval_candidate_limit", self.retrieval_candidate_limit)
        )
        self.retrieval_context_limit = int(
            overrides.get("retrieval_context_limit", self.retrieval_context_limit)
        )
        self.history_token_budget = int(
            overrides.get("prompt_history_token_budget", self.history_token_budget)
        )
        self.context_token_budget = int(
            overrides.get("prompt_context_token_budget", self.context_token_budget)
        )
        if self.retrieval is not None:
            self.retrieval.timeout_seconds = float(
                overrides.get(
                    "retrieval_timeout_seconds", self.retrieval.timeout_seconds
                )
            )

    @staticmethod
    def _assert_knowledge_base_access(
        db: Session, data_owner_id: int, knowledge_base_ids: list[int]
    ) -> None:
        """knowledgeBaseIds 归属校验：请求的知识库必须属于 data_owner_id。

        [] 语义保持「data_owner_id 名下全部知识库」，不做校验。
        跨商家知识库 ID 一律 403，阻止越权检索。
        """
        if not knowledge_base_ids:
            return
        owned_ids = set(
            db.scalars(
                select(KnowledgeBase.id).where(KnowledgeBase.owner_id == data_owner_id)
            )
        )
        for base_id in knowledge_base_ids:
            if base_id not in owned_ids:
                raise AppError(
                    "KNOWLEDGE_BASE_FORBIDDEN", "知识库不存在或无权访问", 403
                )

    @staticmethod
    def _knowledge_diagnostics(
        db: Session, data_owner_id: int, requested_ids: list[int]
    ) -> dict[str, Any]:
        """从数据库实查知识库/文档状态，供 Admin Trace 诊断（不编造）。"""
        owned_ids = set(
            db.scalars(
                select(KnowledgeBase.id).where(KnowledgeBase.owner_id == data_owner_id)
            )
        )
        if requested_ids:
            resolved = sorted(set(requested_ids) & owned_ids)
        else:
            resolved = sorted(owned_ids)
        if not resolved:
            return {
                "resolvedKnowledgeBaseIds": [],
                "eligibleKnowledgeDocuments": 0,
                "indexedKnowledgeDocuments": 0,
                "vectorIndexedDocuments": 0,
                "failedKnowledgeDocuments": 0,
            }
        documents = list(
            db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id.in_(resolved)
                )
            )
        )
        eligible = [item for item in documents if item.enabled]
        indexed = [item for item in eligible if item.status == "indexed"]
        vector_indexed = [item for item in indexed if item.vector_indexed]
        failed = [item for item in documents if item.status == "failed"]
        return {
            "resolvedKnowledgeBaseIds": resolved,
            "eligibleKnowledgeDocuments": len(eligible),
            "indexedKnowledgeDocuments": len(indexed),
            "vectorIndexedDocuments": len(vector_indexed),
            "failedKnowledgeDocuments": len(failed),
        }

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
    def _plain_assistant_prompt(
        request: ChatRequest, history: list[ChatMessage]
    ) -> ModelChatRequest:
        """普通零售运营助手 prompt（无证据上下文）。

        direct 与 refused/escalated 终态共用；history_reference/refuse 的
        占位 model_request 也用同一构造（生成阶段直接输出 prebuilt_answer，
        不会真正调用模型）。
        """
        system_prompt = (
            "你是邻里鲜选 AI 运营助手，可以协助查询商品经营、订单、"
            "售后与知识库相关问题。请用中文简洁友好地回复。"
        )
        messages = [ChatMessage("system", system_prompt)]
        messages.extend(history)
        messages.append(ChatMessage("user", request.question))
        return ModelChatRequest(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            metadata={
                "deep_thinking": request.deep_thinking,
                "requested_mode": "thinking" if request.deep_thinking else "normal",
            },
        )

    @staticmethod
    def _emit_generation_progress(prepared: PreparedChat) -> bool:
        """是否发送 generation running/completed 进度事件。

        research（含 escalate 终态）与 refuse 保留现有事件流：refuse 需在
        Timeline 展示「请求无法执行」状态（现有测试与前端依赖）；direct 与
        history_reference 的 Timeline 对用户隐藏（前端 steps 为空），
        不发送任何 generation progress 事件。
        """
        return prepared.intent in (None, "research", "refuse")

    async def prepare_history_reference_response(
        self,
        db: Session,
        request: ChatRequest,
        trace: TraceExecution,
        conversation: Conversation,
        turn: ConversationTurn,
        user_message: Message,
        request_run_id: int | None,
        budgeted_history: list[ChatMessage],
    ) -> PreparedChat:
        """history_reference：答案来自当前对话本身，不 Rewrite、不 RAG。

        从 budgeted_history 取最近一条 user 消息确定性回答；无历史时兜底
        「当前对话还没有历史消息」。terminal 语义 direct（message_status
        NORMAL），生成阶段直接输出 prebuilt_answer，不调用模型。
        """
        previous_user = next(
            (item for item in reversed(budgeted_history) if item.role == "user"),
            None,
        )
        prebuilt_answer = (
            f"你上一句话问的是：\u201c{previous_user.content}\u201d"
            if previous_user is not None
            else "当前对话还没有历史消息"
        )
        with self.traces.node(db, trace, "prompt") as attributes:
            model_request = self._plain_assistant_prompt(request, budgeted_history)
            attributes.update(
                intent="history_reference",
                original_question=request.question,
                resolved_question=request.question,
                prebuilt=True,
                history_messages_used=len(budgeted_history),
                prompt_messages=len(model_request.messages),
            )
        return PreparedChat(
            conversation.id,
            conversation.title,
            turn,
            user_message.id,
            model_request,
            [],
            request.question,
            trace,
            request_run_id,
            "direct",
            "direct",
            intent="history_reference",
            execution_mode="history_reference",
            prebuilt_answer=prebuilt_answer,
        )

    async def prepare_direct_response(
        self,
        db: Session,
        request: ChatRequest,
        trace: TraceExecution,
        conversation: Conversation,
        turn: ConversationTurn,
        user_message: Message,
        request_run_id: int | None,
        budgeted_history: list[ChatMessage],
    ) -> PreparedChat:
        """direct：不需要商家私有数据/知识库即可回答。

        不 Rewrite、不 Agent；model_request 用普通零售运营助手 prompt
        （无证据上下文）；Timeline 对用户隐藏（生成阶段不发 generation
        progress 事件，token 正常流式）。
        """
        with self.traces.node(db, trace, "prompt") as attributes:
            model_request = self._plain_assistant_prompt(request, budgeted_history)
            attributes.update(
                intent="direct",
                original_question=request.question,
                resolved_question=request.question,
                context_count=0,
                context_chars=0,
                history_messages_used=len(budgeted_history),
                prompt_messages=len(model_request.messages),
                requested_mode="thinking" if request.deep_thinking else "normal",
                reasoning_enabled=request.deep_thinking,
            )
        return PreparedChat(
            conversation.id,
            conversation.title,
            turn,
            user_message.id,
            model_request,
            [],
            request.question,
            trace,
            request_run_id,
            "direct",
            "direct",
            intent="direct",
            execution_mode="direct",
        )

    async def prepare_refusal_response(
        self,
        db: Session,
        request: ChatRequest,
        trace: TraceExecution,
        conversation: Conversation,
        turn: ConversationTurn,
        user_message: Message,
        request_run_id: int | None,
        budgeted_history: list[ChatMessage],
    ) -> PreparedChat:
        """refuse：请求本身不应执行，固定拒绝响应，不 Retrieval。

        prebuilt_answer = build_terminal_response("refused")；生成阶段保留
        generation running/completed 事件（展示「请求无法执行」状态）。
        """
        with self.traces.node(db, trace, "prompt") as attributes:
            model_request = self._plain_assistant_prompt(request, budgeted_history)
            attributes.update(
                intent="refuse",
                original_question=request.question,
                resolved_question=request.question,
                prebuilt=True,
                history_messages_used=len(budgeted_history),
                prompt_messages=len(model_request.messages),
            )
        return PreparedChat(
            conversation.id,
            conversation.title,
            turn,
            user_message.id,
            model_request,
            [],
            request.question,
            trace,
            request_run_id,
            "refuse",
            "refused",
            intent="refuse",
            execution_mode="refuse",
            prebuilt_answer=build_terminal_response("refused"),
        )

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
        actor_user_id: int,
        data_owner_id: int,
        request: ChatRequest,
        trace: TraceExecution,
        progress_sink: ProgressSink | None = None,
    ) -> PreparedChat:
        self._apply_runtime_overrides(db)
        self._assert_knowledge_base_access(db, data_owner_id, request.knowledge_base_ids)
        request_run = self._begin_request(db, actor_user_id, request)
        turn = (
            self.conversations.require_owned_turn(db, request.turn_id, actor_user_id)
            if request.turn_id is not None
            else (
                self.conversations.require_owned_turn(db, request_run.turn_id, actor_user_id)
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
                actor_user_id,
            )
            if (
                request.conversation_id
                or turn is not None
                or (request_run and request_run.conversation_id)
            )
            else self.conversations.create(db, actor_user_id, request.question[:40])
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
                user_id=actor_user_id,
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
            actor_user_id,
            before_sequence=turn.sequence,
        )
        budgeted_history = self._budget_history(history)

        # 意图前置路由（Intent → Rewrite → Research）：只有 research 才继续
        # rewrite/agentic；direct/history_reference/refuse 走确定性快速分支，
        # 不调用改写与 Agent 流程（refuse 同时保证不触发任何 Retrieval）。
        # 同步当前 model_router：运行期/测试可能整体替换 router 实例，
        # 避免构造时的陈旧绑定（否则 classify 会调用旧模型导致意图误判）。
        # 注入的测试替身（非 ConversationIntentRouter）无此属性则跳过。
        # intent-router 单独打点：LLM 分类可能耗时 ~1s+（此前是 Trace 黑盒时间，
        # 总耗时与节点累计的缺口主要来自这里）
        with self.traces.node(db, trace, "intent-router") as attributes:
            if isinstance(self.intent_router, ConversationIntentRouter):
                self.intent_router.model_router = self.model_router
            intent = await self.intent_router.classify(
                request.question, budgeted_history
            )
            attributes.update(intent=intent.intent, reason=intent.reason)
        if intent.intent == "history_reference":
            return await self.prepare_history_reference_response(
                db,
                request,
                trace,
                conversation,
                turn,
                user_message,
                request_run.id if request_run is not None else None,
                budgeted_history,
            )
        if intent.intent == "direct":
            return await self.prepare_direct_response(
                db,
                request,
                trace,
                conversation,
                turn,
                user_message,
                request_run.id if request_run is not None else None,
                budgeted_history,
            )
        if intent.intent == "refuse":
            return await self.prepare_refusal_response(
                db,
                request,
                trace,
                conversation,
                turn,
                user_message,
                request_run.id if request_run is not None else None,
                budgeted_history,
            )

        # 收集本请求的 agent 进度事件（prepare 内部 seq 统一递增），
        # 并透传给外层 sink（stream 层会再次统一编号，最外层编号生效）。
        # 定义在 rewrite 阶段之前：rewrite/planning/tool/review/replan/
        # generation 全部走同一条 collect 流（seq 唯一递增，不重复创建）。
        collected: list[AgentProgressEvent] = []
        seq_counter = itertools.count(1)

        async def collect(event: AgentProgressEvent) -> None:
            event = dict(event)
            event["seq"] = next(seq_counter)
            # 与计数 sink 的毫秒单位保持一致，保证非流式 complete() 路径的
            # durationMs 与 SSE 路径同单位
            event["timestamp"] = round(time.time() * 1000, 3)
            collected.append(event)
            if progress_sink is not None:
                await progress_sink(event)

        with self.traces.node(db, trace, "rewrite") as attributes:
            rewrite = (
                await self.rewrite.rewrite(
                    request.question,
                    [(item.role, item.content) for item in budgeted_history],
                    progress=collect,
                )
                if request.rag_enabled
                else RewriteResult(
                    request.question, request.question, skip_reason="rag_disabled"
                )
            )
            attributes.update(
                actorUserId=actor_user_id,
                dataOwnerId=data_owner_id,
                rewritten_query=rewrite.rewritten_query,
                original_question=request.question,
                resolved_question=rewrite.rewritten_query,
                intent="research",
                fallback=rewrite.used_fallback,
                skip_reason=rewrite.skip_reason,
                history_messages=len(budgeted_history),
            )

        documents: list[SearchResult] = []
        # agent 模式/终态：agentic 路径来自 run() 结果；非 agentic（retrieval
        # 回退）统一按 research/grounded 处理（保持现有证据上下文生成路径，
        # 简化处理，不按 0 条结果细分 escalate）。
        agent_mode: str = "research"
        agent_terminal_state: str = "grounded"
        with self.traces.node(db, trace, "retrieval") as attributes:
            kb_diagnostics = self._knowledge_diagnostics(
                db, data_owner_id, request.knowledge_base_ids
            )
            if request.rag_enabled and self.agentic is not None:
                agent_run = await self.agentic.run(
                    db,
                    actor_user_id=actor_user_id,
                    data_owner_id=data_owner_id,
                    question=rewrite.rewritten_query,
                    original_question=request.question,
                    knowledge_base_ids=tuple(request.knowledge_base_ids),
                    progress_sink=collect,
                )
                agent_mode = agent_run.decision.mode
                agent_terminal_state = agent_run.terminal_state
                documents = self._budget_documents(list(agent_run.results))
                # 把 tool 执行诊断平铺，并带上所属 plan 号与 query
                # （diagnostics 内不含这两项，从 tools step / arguments 补齐），
                # 供 knowledge.search 多轮（multi-plan）聚合使用。
                tool_diagnostics = [
                    {
                        "tool": execution.get("tool"),
                        "plan": step.get("plan"),
                        "query": (execution.get("arguments") or {}).get("query"),
                        **execution.get("diagnostics", {}),
                    }
                    for step in agent_run.steps
                    if step.get("agent") == "tools"
                    for execution in step.get("executions", [])
                ]
                knowledge_calls = [
                    item
                    for item in tool_diagnostics
                    if item.get("tool") == "knowledge.search"
                ]
                # 全部 knowledge.search 调用按 plan 聚合（replan 后 plan 递增）。
                knowledge_search_calls = [
                    {
                        "plan": item.get("plan"),
                        "query": item.get("query"),
                        "keywordCount": item.get("keywordCount"),
                        "vectorCount": item.get("vectorCandidateCount"),
                        "finalCount": item.get("finalCount"),
                        "channelErrors": item.get("channelErrors") or {},
                    }
                    for item in sorted(
                        knowledge_calls, key=lambda item: item.get("plan") or 0
                    )
                ]
                # 兼容保留：keywordCandidateCount 等标量取第一次 knowledge.search
                # 诊断（历史语义），完整多轮信息见 knowledgeSearchCalls 数组。
                knowledge_diag = next(iter(knowledge_calls), None)
                review = agent_run.review_details
                attributes.update(
                    agentic=True,
                    mode=agent_run.decision.mode,
                    selected_tools=list(agent_run.decision.tools),
                    rationale=agent_run.decision.rationale,
                    evidence_review=agent_run.review,
                    react_steps=list(agent_run.steps),
                    result_count=len(documents),
                    actorUserId=actor_user_id,
                    dataOwnerId=data_owner_id,
                    requestedKnowledgeBaseIds=list(request.knowledge_base_ids),
                    resolvedKnowledgeBaseIds=kb_diagnostics["resolvedKnowledgeBaseIds"],
                    eligibleKnowledgeDocuments=kb_diagnostics["eligibleKnowledgeDocuments"],
                    indexedKnowledgeDocuments=kb_diagnostics["indexedKnowledgeDocuments"],
                    vectorIndexedDocuments=kb_diagnostics["vectorIndexedDocuments"],
                    failedKnowledgeDocuments=kb_diagnostics["failedKnowledgeDocuments"],
                    knowledgeSearchCalls=knowledge_search_calls,
                    lastKnowledgeSearch=(
                        knowledge_search_calls[-1] if knowledge_search_calls else None
                    ),
                    knowledgeSearchTotalCount=len(knowledge_search_calls),
                    # reviewer 事实类型集合：区分「真的 0 results」与
                    # 「有 results 但 evidence type 不满足」（目标: Admin Trace）。
                    presentFactTypes=list(
                        getattr(review, "present_fact_types", ())
                    ),
                    requiredFactTypes=list(
                        getattr(review, "required_fact_types", ())
                    ),
                    auxiliaryFactTypes=list(
                        getattr(review, "auxiliary_fact_types", ())
                    ),
                    keywordCandidateCount=(
                        knowledge_diag.get("keywordCount")
                        if knowledge_diag is not None
                        else None
                    ),
                    keywordError=(
                        knowledge_diag.get("keywordError")
                        if knowledge_diag is not None
                        else None
                    ),
                    vectorEnabled=(
                        knowledge_diag.get("vectorEnabled")
                        if knowledge_diag is not None
                        else None
                    ),
                    vectorCandidateCount=(
                        knowledge_diag.get("vectorCandidateCount")
                        if knowledge_diag is not None
                        else None
                    ),
                    vectorError=(
                        knowledge_diag.get("vectorError")
                        if knowledge_diag is not None
                        else None
                    ),
                    postprocessorFinalCount=(
                        knowledge_diag.get("finalCount")
                        if knowledge_diag is not None
                        else None
                    ),
                    finalContextCount=len(documents),
                    keywordDegraded=bool(
                        knowledge_diag is not None
                        and knowledge_diag.get("keywordError")
                        and int(knowledge_diag.get("finalCount") or 0) > 0
                    ),
                )
            elif request.rag_enabled and self.retrieval is not None:
                response = await self.retrieval.retrieve(
                    RetrievalRequest(
                        query=rewrite.rewritten_query,
                        knowledge_base_ids=tuple(str(item) for item in request.knowledge_base_ids),
                        candidate_limit=self.retrieval_candidate_limit,
                        context_limit=self.retrieval_context_limit,
                        metadata={
                            "user_id": actor_user_id,
                            "owner_id": data_owner_id,
                        },
                    )
                )
                documents = self._budget_documents(response.results)
                keyword_outcome = next(
                    (
                        outcome
                        for outcome in response.outcomes
                        if outcome.channel == "keyword"
                    ),
                    None,
                )
                vector_outcome = next(
                    (
                        outcome
                        for outcome in response.outcomes
                        if outcome.channel == "vector"
                    ),
                    None,
                )
                attributes.update(
                    result_count=len(documents),
                    elapsed_ms=response.elapsed_ms,
                    requested_knowledge_base_ids=request.knowledge_base_ids,
                    resolved_knowledge_base_ids=request.knowledge_base_ids,
                    actorUserId=actor_user_id,
                    dataOwnerId=data_owner_id,
                    requestedKnowledgeBaseIds=list(request.knowledge_base_ids),
                    resolvedKnowledgeBaseIds=kb_diagnostics["resolvedKnowledgeBaseIds"],
                    eligibleKnowledgeDocuments=kb_diagnostics["eligibleKnowledgeDocuments"],
                    indexedKnowledgeDocuments=kb_diagnostics["indexedKnowledgeDocuments"],
                    vectorIndexedDocuments=kb_diagnostics["vectorIndexedDocuments"],
                    failedKnowledgeDocuments=kb_diagnostics["failedKnowledgeDocuments"],
                    keywordCandidateCount=(
                        len(keyword_outcome.results)
                        if keyword_outcome is not None
                        else None
                    ),
                    keywordError=keyword_outcome.error if keyword_outcome else None,
                    vectorEnabled=vector_outcome is not None,
                    vectorCandidateCount=(
                        len(vector_outcome.results) if vector_outcome is not None else None
                    ),
                    vectorError=vector_outcome.error if vector_outcome else None,
                    postprocessorFinalCount=len(response.results),
                    finalContextCount=len(documents),
                    keywordDegraded=bool(
                        keyword_outcome is not None
                        and keyword_outcome.error
                        and response.results
                    ),
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
            # 生成阶段的 system prompt 按 agent 终态选择（complete/stream 共用
            # 同一策略）：direct 与 refused/escalated 不拼接检索证据上下文
            # （普通零售运营助手 prompt，复用意图层 direct 分支的同一构造）；
            # refused/escalated 的 model_request 仅占位保持类型完整，生成阶段
            # 不会调用模型（直接输出固定文案）。
            if agent_terminal_state in ("direct", "refused", "escalated"):
                model_request = self._plain_assistant_prompt(request, budgeted_history)
                context = ""
            else:
                # 与 Eval 共享同一 Prompt 构造（answer_runtime）：评测的就是
                # 线上用户真正看到的最终回答所依赖的同一输入。
                context = "\n\n".join(
                    f"[资料 {index}] {item.content}"
                    for index, item in enumerate(documents, start=1)
                )
                model_request = GroundedAnswerRuntime.build_grounded_request(
                    question=request.question,
                    evidence=documents,
                    history=budgeted_history,
                    deep_thinking=request.deep_thinking,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
            attributes.update(
                intent="research",
                original_question=request.question,
                resolved_question=rewrite.rewritten_query,
                context_count=len(documents),
                context_chars=len(context),
                context_tokens=count_tokens(context),
                history_messages_used=len(budgeted_history),
                history_tokens=sum(count_tokens(item.content) for item in budgeted_history),
                prompt_messages=len(model_request.messages),
                requested_mode="thinking" if request.deep_thinking else "normal",
                reasoning_enabled=request.deep_thinking,
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
            agent_mode,
            agent_terminal_state,
            agent_execution_events=collected,
            intent="research",
            execution_mode="research",
        )

    @staticmethod
    def _terminal_message_status(terminal: str | None) -> str:
        """agent 终态 → 持久化 message_status。

        refused → REJECTED（受限结果，不协助执行）；escalated → ESCALATED
        （资料不足升级人工）；其余（direct/grounded）→ NORMAL。
        调用方在 interrupted 场景保留 INTERRUPTED 优先。
        """
        if terminal == "refused":
            return "REJECTED"
        if terminal == "escalated":
            return "ESCALATED"
        return "NORMAL"

    @staticmethod
    def _persist_agent_execution(
        db: Session,
        message: Message,
        events: list[AgentProgressEvent],
        *,
        commit: bool = True,
        final_status: str | None = None,
    ) -> None:
        """把 sanitized 执行摘要（reducer 合并）写回 assistant 消息；无事件时跳过。"""
        summary = build_execution_summary(events, final_status)
        if summary is None:
            return
        message.agent_execution_json = json.dumps(summary, ensure_ascii=False)
        if commit:
            db.commit()

    def require_router(self) -> ChatModelRouter:
        if self.model_router is None:
            raise ProviderUnavailableError("尚未配置 LLM API Key")
        return self.model_router

    async def complete(
        self,
        db: Session,
        actor_user_id: int,
        data_owner_id: int,
        request: ChatRequest,
    ) -> ChatResponse:
        cached = self._cached_message(db, actor_user_id, request)
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
        trace = self.traces.start(
            db,
            user_id=actor_user_id,
            query=request.question,
            request_id=request.request_id,
        )
        try:
            prepared = await self.prepare(
                db, actor_user_id, data_owner_id, request, trace
            )
        except Exception as exc:
            if not isinstance(exc, AppError) or exc.code != "REQUEST_IN_PROGRESS":
                run = (
                    self._request_run(db, actor_user_id, request.request_id)
                    if request.request_id
                    else None
                )
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
            terminal = prepared.agent_terminal_state
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                attributes["terminal_mode"] = terminal
                if prepared.prebuilt_answer is not None:
                    # history_reference / refuse：不调用模型，直接输出确定性文本
                    answer = prepared.prebuilt_answer
                elif terminal in ("refused", "escalated"):
                    # terminal 状态：不调用模型，直接输出固定文案
                    answer = build_terminal_response(terminal)
                else:
                    answer = await self.require_router().complete(prepared.model_request)
                attributes["answer_chars"] = len(answer)
            # generation 事件携带最终 plan 编号（multi-plan 顺序修复的数据端）
            final_plan = max(
                (
                    event.get("plan") or 1
                    for event in prepared.agent_execution_events
                    if event.get("phase") == "planning"
                ),
                default=1,
            )
            # generation 阶段事件：running → completed（seq 接续 prepare 编号）。
            # direct/history_reference 的 Timeline 对用户隐藏（前端 steps 为空），
            # 不发送 generation 事件；refuse 保留（展示「请求无法执行」状态）。
            if self._emit_generation_progress(prepared):
                for generation_status, generation_title in (
                    ("running", phase_text("generation", "running")),
                    ("completed", phase_text("generation", "completed")),
                ):
                    prepared.agent_execution_events.append(
                        {
                            "seq": len(prepared.agent_execution_events) + 1,
                            "phase": "generation",
                            "status": generation_status,
                            "agent": "generator",
                            "plan": final_plan,
                            "title": generation_title,
                            "timestamp": round(time.time() * 1000, 3),
                        }
                    )
            # complete 阶段事件携带 terminal + intent，供 summary 持久化
            # terminalState / intent（与 stream() 成功路径的 complete 事件同一契约）。
            prepared.agent_execution_events.append(
                {
                    "seq": len(prepared.agent_execution_events) + 1,
                    "phase": "complete",
                    "status": "completed",
                    "agent": "generator",
                    "title": phase_text("complete", "completed"),
                    "detail": "回答生成完成",
                    "terminal": terminal,
                    "intent": prepared.intent,
                    "timestamp": round(time.time() * 1000, 3),
                }
            )
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=actor_user_id,
                content=answer,
                citations=prepared.citations,
                message_status=self._terminal_message_status(terminal),
            )
            self._persist_agent_execution(db, message, prepared.agent_execution_events)
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
        actor_user_id: int,
        data_owner_id: int,
        request: ChatRequest,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict]:
        cached = self._cached_message(db, actor_user_id, request)
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
        trace = self.traces.start(
            db,
            user_id=actor_user_id,
            query=request.question,
            request_id=request.request_id,
        )
        queue: asyncio.Queue[dict] = asyncio.Queue()
        # 流级事件收集：prepare 与 generation 的全部事件以统一 seq（计数 sink）
        # 进入 persist_events，流结束（成功/异常）后做 reducer 合并持久化。
        persist_events: list[AgentProgressEvent] = []

        async def enqueue(event: AgentProgressEvent) -> None:
            persist_events.append(dict(event))
            await queue.put(dict(event))

        # prepare 内部与 generation 的事件共享同一计数 sink（seq 全流唯一递增）
        emit = make_counting_sink(enqueue)
        prepare_task = asyncio.create_task(
            self.prepare(db, actor_user_id, data_owner_id, request, trace, progress_sink=emit)
        )
        try:
            # prepare 执行期间实时转发 progress 事件
            while not prepare_task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                yield {"type": "agent_progress", "data": event}
            while True:
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield {"type": "agent_progress", "data": event}
            prepared = await prepare_task
            # generation 事件携带最终 plan 编号（multi-plan 顺序修复的数据端）
            final_plan = max(
                (
                    event.get("plan") or 1
                    for event in prepared.agent_execution_events
                    if event.get("phase") == "planning"
                ),
                default=1,
            )
        except (GeneratorExit, asyncio.CancelledError):
            # 客户端断开/任务取消：取消 prepare 任务，防止 dangling task
            if not prepare_task.done():
                prepare_task.cancel()
                await asyncio.gather(prepare_task, return_exceptions=True)
            # 取消发生在 prepare 期间：请求记录与 trace 也要收尾，
            # 否则 ChatRequestRun 停留 processing（5 分钟内同 requestId 被 REQUEST_IN_PROGRESS 拦截）
            if request.request_id:
                run = self._request_run(db, actor_user_id, request.request_id)
                if run is not None and run.status == "processing":
                    self._finish_request(db, run.id, status="cancelled")
            self.traces.finish(
                db,
                trace,
                conversation_id=trace.run.conversation_id or request.conversation_id,
                rewritten_query=request.question,
                turn_id=trace.run.turn_id,
                status="cancelled",
            )
            raise
        except BaseException as exc:
            # prepare 失败：清理任务后沿用原有失败处理，异常上抛给 API 转 error 事件
            if not prepare_task.done():
                prepare_task.cancel()
                await asyncio.gather(prepare_task, return_exceptions=True)
            if not isinstance(exc, AppError) or exc.code != "REQUEST_IN_PROGRESS":
                run = self._request_run(db, actor_user_id, request.request_id) if request.request_id else None
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

        async def emit_event(event: AgentProgressEvent) -> AsyncIterator[dict]:
            """发送一条 progress 事件并把积压队列全部转发（generation 阶段无泵循环）。"""
            await emit(event)
            while True:
                try:
                    queued = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield {"type": "agent_progress", "data": queued}

        try:
            interrupted = False
            terminal = prepared.agent_terminal_state
            generation_started_at = time.perf_counter()
            first_token_at: float | None = None
            thinking_started_at: float | None = None
            thinking_finished_at: float | None = None
            # direct/history_reference 的 Timeline 对用户隐藏（前端 steps 为空），
            # 不发送 generation running；research/refuse 保持现有事件流
            # （refuse 需展示「请求无法执行」状态）。
            if self._emit_generation_progress(prepared):
                async for item in emit_event(
                    {
                        "phase": "generation",
                        "status": "running",
                        "agent": "generator",
                        "plan": final_plan,
                        "title": phase_text("generation", "running"),
                    }
                ):
                    yield item
            with self.traces.node(db, prepared.trace, "generation") as attributes:
                if prepared.prebuilt_answer is not None:
                    # history_reference / refuse：不进入 router.stream 循环
                    # （不调用模型）。固定文案在 generation running 之后按句子
                    # 作为 token 输出（不变量：正文不得出现在「回答生成完成」
                    # 之后），answer_parts 累计保持一致，SSE 生命周期正常完结。
                    text = prepared.prebuilt_answer
                    answer_parts.append(text)
                    attributes.update(
                        answer_chars=len(text),
                        interrupted=False,
                        terminal_mode=terminal,
                    )
                    for part in _split_terminal_text(text):
                        yield {"type": "token", "data": part}
                elif terminal in ("refused", "escalated"):
                    # terminal 状态：不进入 router.stream 循环（不调用模型）。
                    # 固定文案在 generation running 之后立即按句子作为 token
                    # 输出（不变量：conversation < generation running < token
                    # < generation completed < complete < done，正文不得出现在
                    # 「回答生成完成」之后），answer_parts 累计保持一致，
                    # SSE 生命周期正常完结。
                    text = build_terminal_response(terminal)
                    answer_parts.append(text)
                    attributes.update(
                        answer_chars=len(text),
                        interrupted=False,
                        terminal_mode=terminal,
                    )
                    for part in _split_terminal_text(text):
                        yield {"type": "token", "data": part}
                else:
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
                            # direct 不发 generation 进度事件（Timeline 隐藏）
                            if self._emit_generation_progress(prepared):
                                async for item in emit_event(
                                    {
                                        "phase": "generation",
                                        "status": "running",
                                        "agent": "generator",
                                        "plan": final_plan,
                                        "title": "正在生成回答",
                                        "detail": "回答内容正在生成中",
                                    }
                                ):
                                    yield item
                        answer_parts.append(token)
                        yield {"type": "token", "data": token}
                    interrupted = bool(cancel_event is not None and cancel_event.is_set())
                    ttft_ms = (
                        round((first_token_at - generation_started_at) * 1000, 2)
                        if first_token_at is not None
                        else None
                    )
                    attributes.update(
                        answer_chars=sum(map(len, answer_parts)),
                        interrupted=interrupted,
                        ttft_ms=ttft_ms,
                        requested_mode=prepared.model_request.metadata.get("requested_mode"),
                        reasoning_enabled=prepared.model_request.metadata.get("deep_thinking", False),
                        thinking_chars=sum(map(len, thinking_parts)),
                        terminal_mode=terminal,
                    )
                    # Run 级 TTFT：列表 API 直接读取（trace.finish 的 commit 落库）
                    prepared.trace.run.ttft_ms = ttft_ms
            answer = "".join(answer_parts)
            if not interrupted:
                # 回答生成完成（generation completed）先于 complete 事件下发；
                # direct/history_reference 不发 generation 事件（Timeline 隐藏）
                if self._emit_generation_progress(prepared):
                    async for item in emit_event(
                        {
                            "phase": "generation",
                            "status": "completed",
                            "agent": "generator",
                            "plan": final_plan,
                            "title": phase_text("generation", "completed"),
                        }
                    ):
                        yield item
                async for item in emit_event(
                    {
                        "phase": "complete",
                        "status": "completed",
                        "agent": "generator",
                        "title": phase_text("complete", "completed"),
                        "detail": "回答生成完成",
                        "terminal": terminal,
                        "intent": prepared.intent,
                    }
                ):
                    yield item
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=actor_user_id,
                content=answer,
                citations=prepared.citations,
                message_status=(
                    "INTERRUPTED"
                    if interrupted
                    else self._terminal_message_status(terminal)
                ),
                thinking_content="".join(thinking_parts) or None,
                thinking_duration_ms=(
                    round((thinking_finished_at - thinking_started_at) * 1000)
                    if thinking_started_at is not None and thinking_finished_at is not None
                    else None
                ),
            )
            self._persist_agent_execution(
                db,
                message,
                persist_events,
                final_status="cancelled" if interrupted else None,
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
                    # SSE finish 透传持久化 message_status（NORMAL/REJECTED/
                    # ESCALATED/INTERRUPTED），前端无需等重载即可展示受限结果文案
                    "message_status": message.message_status,
                },
            }
        except BaseException as exc:
            answer = "".join(answer_parts)
            cancelled = isinstance(exc, (GeneratorExit, asyncio.CancelledError))
            message = self.conversations.add_assistant_version(
                db,
                turn=prepared.turn,
                user_id=actor_user_id,
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
            self._persist_agent_execution(
                db,
                message,
                persist_events,
                commit=False,
                final_status="cancelled" if cancelled else "failed",
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
