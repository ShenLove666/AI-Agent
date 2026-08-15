import { create } from "zustand";
import { toast } from "sonner";

import type {
  AgentExecutionStep,
  AgentProgressPayload,
  CompletionPayload,
  FeedbackValue,
  Message,
  MessageDeltaPayload,
  Session
} from "@/types";
import type { ConversationMessageVO } from "@/services/sessionService";
import {
  listMessages,
  listSessions,
  deleteSession as deleteSessionRequest,
  renameSession as renameSessionRequest
} from "@/services/sessionService";
import {
  stopTask,
  submitFeedback,
  cancelFeedback,
  generateRecommendedQuestions,
} from "@/services/chatService";
import { createStreamResponse } from "@/hooks/useStreamResponse";
import {
  cancelAgentSteps,
  computeAgentExecutionSummary,
  restoreAgentExecution
} from "@/utils/agentExecution";
import {
  disposeAgentProgressScheduler,
  getAgentProgressScheduler,
  hasAgentProgressScheduler
} from "@/utils/agentProgressPresentation";
import { storage } from "@/utils/storage";
import { API_BASE_URL } from "@/services/api";

interface ChatState {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  isLoading: boolean;
  sessionsLoaded: boolean;
  inputFocusKey: number;
  isStreaming: boolean;
  isCreatingNew: boolean;
  deepThinkingEnabled: boolean;
  knowledgeBaseIds: string[];
  thinkingStartAt: number | null;
  streamTaskId: string | null;
  streamAbort: (() => void) | null;
  streamingMessageId: string | null;
  cancelRequested: boolean;
  openedSourceMessageId: string | null;
  // 展开推荐面板后需滚入视口的消息；每次请求都是新对象，供 MessageList 一次性响应
  recommendReveal: { id: string } | null;
  fetchSessions: () => Promise<void>;
  createSession: () => Promise<string>;
  deleteSession: (sessionId: string) => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  updateSessionTitle: (sessionId: string, title: string) => void;
  setDeepThinkingEnabled: (enabled: boolean) => void;
  setKnowledgeBaseIds: (ids: string[]) => void;
  sendMessage: (content: string) => Promise<void>;
  cancelGeneration: () => void;
  appendStreamContent: (delta: string) => void;
  appendThinkingContent: (delta: string) => void;
  submitFeedback: (messageId: string, feedback: FeedbackValue) => Promise<void>;
  toggleSourcesPanel: (messageId: string) => void;
  openSourcesPanel: (messageId: string) => void;
  closeSourcesPanel: () => void;
  loadRecommended: (messageId: string) => Promise<void>;
  toggleRecommended: (messageId: string) => void;
  regenerateTurn: (turnId: number) => Promise<void>;
}

function mapVoteToFeedback(vote?: number | null): FeedbackValue {
  if (vote === 1) return "like";
  if (vote === -1) return "dislike";
  return null;
}

function mapPersistedMessageStatus(status?: Message["messageStatus"] | null): Message["status"] {
  if (status === "INTERRUPTED") return "cancelled";
  if (status === "ERROR") return "error";
  // REJECTED/ESCALATED 是受限结果而非系统错误：按完成态展示（ERROR 仍 → error）
  return "done";
}

function failLastRunningStep(steps?: AgentExecutionStep[]): AgentExecutionStep[] | undefined {
  if (!steps || steps.length === 0) return steps;
  const lastRunningIndex = steps.reduce(
    (found, step, index) => (step.status === "running" ? index : found),
    -1
  );
  if (lastRunningIndex < 0) return steps;
  return steps.map((step, index) =>
    index === lastRunningIndex ? { ...step, status: "failed" as const } : step
  );
}

function upsertSession(sessions: Session[], next: Session) {
  const index = sessions.findIndex((session) => session.id === next.id);
  const updated = [...sessions];
  if (index >= 0) {
    updated[index] = { ...sessions[index], ...next };
  } else {
    updated.unshift(next);
  }
  return updated.sort((a, b) => {
    const timeA = a.lastTime ? new Date(a.lastTime).getTime() : 0;
    const timeB = b.lastTime ? new Date(b.lastTime).getTime() : 0;
    return timeB - timeA;
  });
}

function computeThinkingDuration(startAt?: number | null) {
  if (!startAt) return undefined;
  const seconds = Math.round((Date.now() - startAt) / 1000);
  return Math.max(1, seconds);
}

function feedbackForMessage(messages: Message[], messageId: string): FeedbackValue {
  for (const message of messages) {
    if (message.id === messageId) return message.feedback ?? null;
    const version = message.answerVersions?.find((item) => item.id === messageId);
    if (version) return version.feedback ?? null;
  }
  return null;
}

function withMessageFeedback(
  messages: Message[],
  messageId: string,
  feedback: FeedbackValue
): Message[] {
  return messages.map((message) => ({
    ...message,
    feedback: message.id === messageId ? feedback : message.feedback,
    answerVersions: message.answerVersions?.map((version) =>
      version.id === messageId ? { ...version, feedback } : version
    )
  }));
}

function mapConversationMessages(data: ConversationMessageVO[]): Message[] {
  return data.map((item) => ({
    id: String(item.id),
    role: item.role === "assistant" ? "assistant" : "user",
    content: item.content,
    thinking: item.thinkingContent || undefined,
    thinkingDuration: item.thinkingDuration || undefined,
    isDeepThinking: Boolean(item.thinkingContent),
    createdAt: item.createTime,
    feedback: mapVoteToFeedback(item.vote),
    status: mapPersistedMessageStatus(item.messageStatus),
    sources: item.sources || undefined,
    recommended: item.recommendedQuestions ?? undefined,
    recommendedState:
      item.recommendedQuestionsStatus === "FAILED"
        ? "error"
        : item.recommendedQuestionsStatus === "SUCCESS" ||
            item.recommendedQuestionsStatus === "EMPTY"
          ? "ready"
          : undefined,
    messageStatus: item.messageStatus ?? "NORMAL",
    turnId: item.turnId ?? undefined,
    version: item.version ?? undefined,
    answerVersions: item.answerVersions,
    // 老消息无 agent_execution_json 时保持 undefined，页面正常降级；
    // 整体状态由持久化 messageStatus 推导（INTERRUPTED→cancelled /
    // ERROR→failed；REJECTED/ESCALATED 受限结果 → completed）
    ...restoreAgentExecution(item.agentExecutionJson, item.messageStatus)
  }));
}

export const useChatStore = create<ChatState>((set, get) => {
  // Loading a conversation is not cancellable through the current service
  // contract.  Keep a request sequence so a slower, older response can never
  // clear the loading state or replace the conversation selected afterwards.
  let sessionLoadSequence = 0;

  const invalidateSessionLoad = () => {
    sessionLoadSequence += 1;
    return sessionLoadSequence;
  };

  /**
   * 应用单条 agent_progress 事件到当前流式消息。
   * - 仅更新 streamingMessageId 对应的 assistant 消息（老请求不污染新请求）
   * - 逻辑合并（stepId 原地更新/seq 去重/complete 收尾）统一由 AgentProgressScheduler
   *   完成：running 立即可见，终态按 minRunningVisibleMs 延迟揭示，
   *   保证 running 至少有一次独立 paint（避免一次 reader.read() 多事件同 tick 批量渲染）
   * - scheduler 与 streamingMessageId 一一对应（request-scoped），流收尾时 dispose
   */
  const handleAgentProgress = (payload: AgentProgressPayload) => {
    const { streamingMessageId } = get();
    if (!streamingMessageId) return;
    const target = get().messages.find((message) => message.id === streamingMessageId);
    // 消息已被替换（会话切换/重新加载）或已结束（取消/失败）时忽略后续事件
    if (!target || target.role !== "assistant") return;
    if (target.agentExecutionStatus !== "running") return;
    const scheduler = getAgentProgressScheduler(streamingMessageId, {
      onChange: (steps) =>
        set((state) => ({
          // 用 state.streamingMessageId 判断：streamingMessageId 已被清空/切换时不再写入
          messages: state.messages.map((message) =>
            message.id === state.streamingMessageId ? { ...message, agentSteps: steps } : message
          )
        }))
    });
    scheduler.push(payload);
    // 契约扩展（并行后端在改）：planning completed 携带 mode、complete 携带 terminal 与 intent。
    // scheduler 的 onChange 只写 agentSteps，mode/terminal/intent 单独 set 到消息，避免互相覆盖；
    // set 内用 state.streamingMessageId 守卫，与 onChange 的写入条件保持一致
    const nextMode =
      payload.phase === "planning" && payload.status === "completed" ? payload.mode : undefined;
    const nextTerminal = payload.phase === "complete" ? payload.terminal : undefined;
    const nextIntent = payload.phase === "complete" ? payload.intent : undefined;
    if (nextMode || nextTerminal || nextIntent) {
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === state.streamingMessageId
            ? {
                ...message,
                ...(nextMode ? { agentExecutionMode: nextMode } : {}),
                ...(nextTerminal ? { agentTerminalState: nextTerminal } : {}),
                ...(nextIntent ? { agentIntent: nextIntent } : {})
              }
            : message
        )
      }));
    }
  };

  /**
   * 共享流式链路：发送新消息与重新生成都走这里。
   * - 建立 SSE 流并实时应用 agent_progress / token / thinking / finish 等事件
   * - userPlaceholderId 为 sendMessage 的本地 user 占位 id（onMeta 时替换为后端 id）；
   *   regenerate 场景传 undefined（原 user 消息已是后端 id）
   */
  async function runAssistantStream(opts: {
    payload: Record<string, unknown>;
    assistantId: string;
    userPlaceholderId?: string;
  }) {
    const { payload, assistantId, userPlaceholderId } = opts;
    const url = `${API_BASE_URL}/rag/v3/chat`;
    const token = storage.getToken();

    const handlers = {
      onMeta: (metaPayload: import("@/types").StreamMetaPayload) => {
        if (get().streamingMessageId !== assistantId) return;
        const nextId = metaPayload.conversationId || get().currentSessionId;
        // 连接即推送的早期 meta 只有 taskId：先无条件登记，让「停止生成」能立即命中任务
        set({ streamTaskId: metaPayload.taskId });
        if (!metaPayload.conversationId) {
          // 会话信息尚未就绪（后续全量 meta 才带 conversationId）；
          // 若用户已点停止，先请求服务端停止该任务
          if (get().cancelRequested) {
            stopTask(metaPayload.taskId).catch(() => null);
          }
          return;
        }
        if (!nextId) return;
        const lastTime = new Date().toISOString();
        const existing = get().sessions.find((session) => session.id === nextId);
        set((state) => ({
          currentSessionId: nextId,
          isCreatingNew: false,
          streamTaskId: metaPayload.taskId,
          messages: state.messages.map((message) => {
            if (userPlaceholderId && message.id === userPlaceholderId && metaPayload.userMessageId) {
              return {
                ...message,
                id: String(metaPayload.userMessageId),
                turnId: metaPayload.turnId ?? undefined
              };
            }
            if (message.id === assistantId) {
              return { ...message, turnId: metaPayload.turnId ?? undefined };
            }
            return message;
          }),
          sessions: upsertSession(state.sessions, {
            id: nextId,
            title: metaPayload.title || existing?.title || "新对话",
            lastTime
          })
        }));
        if (get().cancelRequested) {
          stopTask(metaPayload.taskId).catch(() => null);
        }
      },
      onMessage: (msgPayload: MessageDeltaPayload) => {
        if (!msgPayload || typeof msgPayload !== "object") return;
        if (msgPayload.type !== "response") return;
        get().appendStreamContent(msgPayload.delta);
      },
      onThinking: (msgPayload: MessageDeltaPayload) => {
        if (!msgPayload || typeof msgPayload !== "object") return;
        if (msgPayload.type !== "think") return;
        get().appendThinkingContent(msgPayload.delta);
      },
      onAgentProgress: (progressPayload: AgentProgressPayload) => {
        if (get().streamingMessageId !== assistantId) return;
        if (!progressPayload || typeof progressPayload !== "object") return;
        handleAgentProgress(progressPayload);
      },
      onReject: (msgPayload: MessageDeltaPayload) => {
        if (!msgPayload || typeof msgPayload !== "object") return;
        get().appendStreamContent(msgPayload.delta);
      },
      onFinish: (finishPayload: CompletionPayload) => {
        if (get().streamingMessageId !== assistantId) return;
        if (!finishPayload) return;
        if (finishPayload.title && get().currentSessionId) {
          get().updateSessionTitle(get().currentSessionId as string, finishPayload.title);
        }
        const currentId = get().currentSessionId;
        if (currentId) {
          const lastTime = new Date().toISOString();
          const existingTitle =
            get().sessions.find((session) => session.id === currentId)?.title || "新对话";
          const nextTitle = finishPayload.title || existingTitle;
          set((state) => ({
            sessions: upsertSession(state.sessions, {
              id: currentId,
              title: nextTitle,
              lastTime
            })
          }));
        }
        // 规范 §49：finish 时若仍有 running 步骤（如 complete 事件丢失），先统一收尾为
        // completed，summary 基于收尾后的步骤计算，避免 toolCallCount 漏计
        const targetMessage = get().messages.find(
          (message) => message.id === get().streamingMessageId
        );
        const finalizedSteps =
          targetMessage?.agentSteps?.map((step) =>
            step.status === "running" ? { ...step, status: "completed" as const } : step
          ) ?? targetMessage?.agentSteps;
        set((state) => ({
          messages: state.messages.map((message) =>
            message.id === state.streamingMessageId
              ? {
                  ...message,
                  id: finishPayload.messageId
                    ? String(finishPayload.messageId)
                    : message.id,
                  status: "done",
                  isThinking: false,
                  sources: finishPayload.sources ?? message.sources,
                  messageStatus: finishPayload.messageStatus ?? "NORMAL",
                  turnId: finishPayload.turnId ?? message.turnId,
                  version: finishPayload.version ?? message.version,
                  thinkingDuration:
                    message.thinkingDuration ?? computeThinkingDuration(state.thinkingStartAt),
                  agentExecutionStatus: "completed",
                  agentSteps: finalizedSteps,
                  agentExecutionSummary: computeAgentExecutionSummary(finalizedSteps)
                }
              : message
          )
        }));
        disposeAgentProgressScheduler(assistantId);
      },
      onCancel: (cancelPayload: CompletionPayload) => {
        if (get().streamingMessageId !== assistantId) return;
        if (cancelPayload?.title && get().currentSessionId) {
          get().updateSessionTitle(get().currentSessionId as string, cancelPayload.title);
        }
        set((state) => ({
          messages: state.messages.map((message) => {
            if (message.id !== state.streamingMessageId) return message;
            const nextId = cancelPayload?.messageId
              ? String(cancelPayload.messageId)
              : message.id;
            return {
              ...message,
              id: nextId,
              content: message.content,
              status: "cancelled",
              isThinking: false,
              sources: cancelPayload?.sources ?? message.sources,
              messageStatus: cancelPayload?.messageStatus ?? "INTERRUPTED",
              turnId: cancelPayload?.turnId ?? message.turnId,
              version: cancelPayload?.version ?? message.version,
              thinkingDuration:
                message.thinkingDuration ?? computeThinkingDuration(state.thinkingStartAt),
              agentSteps: cancelAgentSteps(message.agentSteps),
              agentExecutionStatus: "cancelled"
            };
          }),
          isStreaming: false,
          thinkingStartAt: null,
          streamTaskId: null,
          streamAbort: null,
          streamingMessageId: null,
          cancelRequested: false
        }));
        // SSE cancel 事件 = 流已结束：释放 request-scoped 调度器（幂等）
        disposeAgentProgressScheduler(assistantId);
      },
      onDone: () => {
        if (get().streamingMessageId !== assistantId) return;
        set({
          isStreaming: false,
          thinkingStartAt: null,
          streamTaskId: null,
          streamAbort: null,
          streamingMessageId: null,
          cancelRequested: false
        });
      },
      onTitle: (titlePayload: { title: string }) => {
        if (get().streamingMessageId !== assistantId) return;
        if (titlePayload?.title && get().currentSessionId) {
          get().updateSessionTitle(get().currentSessionId as string, titlePayload.title);
        }
      },
      onError: (error: Error) => {
        if (get().streamingMessageId !== assistantId) return;
        set((state) => ({
          isStreaming: false,
          thinkingStartAt: null,
          streamTaskId: null,
          streamAbort: null,
          cancelRequested: false,
          messages: state.messages.map((message) =>
            message.id === state.streamingMessageId
              ? {
                  ...message,
                  id: (error as Error & { messageId?: string }).messageId || message.id,
                  status: "error",
                  messageStatus: "ERROR",
                  isThinking: false,
                  thinkingDuration:
                    message.thinkingDuration ?? computeThinkingDuration(state.thinkingStartAt),
                  agentSteps: failLastRunningStep(message.agentSteps),
                  agentExecutionStatus: "failed"
                }
              : message
          )
        }));
        toast.error(error.message || "生成失败");
        // 流已失败：释放 request-scoped 调度器（幂等）
        disposeAgentProgressScheduler(assistantId);
      }
    };

    const { start, cancel } = createStreamResponse(
      {
        url,
        method: "POST",
        body: payload,
        headers: token
          ? { Authorization: token.startsWith("Bearer ") ? token : `Bearer ${token}` }
          : undefined,
        // A failed transport must be resumed explicitly with the same requestId;
        // blind GET retries can start duplicate model generations.
        retryCount: 0
      },
      handlers
    );

    set({ streamAbort: cancel });

    try {
      await start();
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        return;
      }
      handlers.onError?.(error as Error);
    } finally {
      if (get().streamingMessageId === assistantId) {
        set({
          isStreaming: false,
          streamTaskId: null,
          streamAbort: null,
          streamingMessageId: null,
          cancelRequested: false
        });
      }
      // 流已收尾（无论 streamingMessageId 是否已被清空/切换），释放 request-scoped
      // 调度器：杜绝定时器/注册表残留（onFinish/onCancel/onError 已 dispose 时幂等）
      disposeAgentProgressScheduler(assistantId);
    }
  }

  return {
  sessions: [],
  currentSessionId: null,
  messages: [],
  isLoading: false,
  sessionsLoaded: false,
  inputFocusKey: 0,
  isStreaming: false,
  isCreatingNew: false,
  deepThinkingEnabled: false,
  knowledgeBaseIds: [],
  thinkingStartAt: null,
  streamTaskId: null,
  streamAbort: null,
  streamingMessageId: null,
  cancelRequested: false,
  openedSourceMessageId: null,
  recommendReveal: null,
  fetchSessions: async () => {
    set({ isLoading: true });
    try {
      const data = await listSessions();
      const sessions = data
        .map((item) => ({
          id: item.conversationId,
          title: item.title || "新对话",
          lastTime: item.lastTime
        }))
        .sort((a, b) => {
          const timeA = a.lastTime ? new Date(a.lastTime).getTime() : 0;
          const timeB = b.lastTime ? new Date(b.lastTime).getTime() : 0;
          return timeB - timeA;
        });
      set({ sessions });
    } catch (error) {
      toast.error((error as Error).message || "加载会话失败");
    } finally {
      set({ isLoading: false, sessionsLoaded: true });
    }
  },
  createSession: async () => {
    invalidateSessionLoad();
    const state = get();
    if (state.messages.length === 0 && !state.currentSessionId) {
      set({
        isCreatingNew: true,
        isLoading: false,
        thinkingStartAt: null,
        deepThinkingEnabled: false,
        openedSourceMessageId: null
      });
      return "";
    }
    if (state.isStreaming) {
      get().cancelGeneration();
    }
    set({
      currentSessionId: null,
      messages: [],
      isStreaming: false,
      isLoading: false,
      isCreatingNew: true,
      deepThinkingEnabled: false,
      thinkingStartAt: null,
      streamTaskId: null,
      streamAbort: null,
      streamingMessageId: null,
      cancelRequested: false,
      openedSourceMessageId: null
    });
    return "";
  },
  deleteSession: async (sessionId) => {
    if (get().currentSessionId === sessionId) {
      invalidateSessionLoad();
    }
    try {
      await deleteSessionRequest(sessionId);
      set((state) => ({
        sessions: state.sessions.filter((session) => session.id !== sessionId),
        messages: state.currentSessionId === sessionId ? [] : state.messages,
        currentSessionId: state.currentSessionId === sessionId ? null : state.currentSessionId,
        isLoading: state.currentSessionId === sessionId ? false : state.isLoading,
        openedSourceMessageId:
          state.currentSessionId === sessionId ? null : state.openedSourceMessageId
      }));
      toast.success("删除成功");
    } catch (error) {
      toast.error((error as Error).message || "删除会话失败");
    }
  },
  renameSession: async (sessionId, title) => {
    const nextTitle = title.trim();
    if (!nextTitle) return;
    try {
      await renameSessionRequest(sessionId, nextTitle);
      set((state) => ({
        sessions: state.sessions.map((session) =>
          session.id === sessionId ? { ...session, title: nextTitle } : session
        )
      }));
      toast.success("已重命名");
    } catch (error) {
      toast.error((error as Error).message || "重命名失败");
    }
  },
  selectSession: async (sessionId) => {
    if (!sessionId) return;
    if (get().currentSessionId === sessionId && get().messages.length > 0) return;
    const requestSequence = invalidateSessionLoad();
    if (get().isStreaming) {
      get().cancelGeneration();
    }
    set({
      isLoading: true,
      currentSessionId: sessionId,
      isCreatingNew: false,
      thinkingStartAt: null,
      openedSourceMessageId: null
    });
    const isCurrentRequest = () =>
      requestSequence === sessionLoadSequence && get().currentSessionId === sessionId;
    try {
      const data = await listMessages(sessionId);
      if (!isCurrentRequest()) return;
      const mapped = mapConversationMessages(data);
      set({ messages: mapped });
    } catch (error) {
      if (isCurrentRequest()) {
        toast.error((error as Error).message || "加载消息失败");
      }
    } finally {
      if (isCurrentRequest()) {
        set({
          isLoading: false,
          isStreaming: false,
          streamTaskId: null,
          streamAbort: null,
          streamingMessageId: null,
          cancelRequested: false
        });
      }
    }
  },
  updateSessionTitle: (sessionId, title) => {
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === sessionId ? { ...session, title } : session
      )
    }));
  },
  setDeepThinkingEnabled: (enabled) => {
    set({ deepThinkingEnabled: enabled });
  },
  setKnowledgeBaseIds: (ids) => {
    set({ knowledgeBaseIds: ids });
  },
  sendMessage: async (content) => {
    const trimmed = content.trim();
    if (!trimmed) return;
    if (get().isStreaming) return;
    const deepThinkingEnabled = get().deepThinkingEnabled;
    const knowledgeBaseIds = get().knowledgeBaseIds;
    const inputFocusKey = Date.now();
    const requestId =
      globalThis.crypto?.randomUUID?.() ||
      `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      status: "done",
      createdAt: new Date().toISOString()
    };
    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      // isDeepThinking 表示「用户本次开启了深度思考模式」；
      // isThinking 表示「后端现在真的正在返回 thinking 流」——两者不能同值。
      // 未收到第一条真实 thinking chunk 前，不制造空的 thinking 状态。
      thinking: undefined,
      isDeepThinking: deepThinkingEnabled,
      isThinking: false,
      status: "streaming",
      feedback: null,
      agentSteps: [],
      agentExecutionStatus: "running",
      createdAt: new Date().toISOString()
    };

    set((state) => ({
      // 新问题发出即收起所有历史消息的推荐面板 保持焦点在最新一轮问答
      messages: [
        ...state.messages.map((message) =>
          message.recommendedOpen ? { ...message, recommendedOpen: false } : message
        ),
        userMessage,
        assistantMessage
      ],
      isStreaming: true,
      streamingMessageId: assistantId,
      thinkingStartAt: null,
      inputFocusKey,
      streamTaskId: null,
      cancelRequested: false
    }));

    const conversationId = get().currentSessionId;
    const streamPayload = {
      question: trimmed,
      conversationId: conversationId || undefined,
      requestId,
      deepThinking: deepThinkingEnabled ? true : undefined,
      knowledgeBaseIds: knowledgeBaseIds.map(Number)
    };
    await runAssistantStream({
      payload: streamPayload,
      assistantId,
      userPlaceholderId: userMessage.id
    });
  },
  cancelGeneration: () => {
    const { isStreaming, streamTaskId, streamingMessageId, streamAbort } = get();
    if (!isStreaming) return;
    set({ cancelRequested: true });
    if (streamingMessageId) {
      // 用户主动停止：立即本地收尾（status/messageStatus 也同步置为 cancelled，
      // 避免 abort 后消息永远停留在 streaming），running 步骤标记 cancelled，
      // 后续 agent_progress 事件被忽略
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === streamingMessageId
            ? {
                ...message,
                status: "cancelled",
                messageStatus: "INTERRUPTED",
                isThinking: false,
                agentSteps: cancelAgentSteps(message.agentSteps),
                agentExecutionStatus: "cancelled"
              }
            : message
        )
      }));
      // 如 request-scoped 调度器存在：同步收敛内部 pending/running（running → cancelled），
      // 避免其定时器在取消后仍触发 emit；不在此 dispose，流最终收尾（finally）统一处理
      if (hasAgentProgressScheduler(streamingMessageId)) {
        getAgentProgressScheduler(streamingMessageId, { onChange: () => {} }).cancel();
      }
    }
    if (streamTaskId) {
      stopTask(streamTaskId).catch(() => null);
    }
    // 立即断开 SSE 连接：让服务器在 prepare 阶段也能真正取消（仅靠 /stop 在前半段无效）
    streamAbort?.();
  },
  appendStreamContent: (delta) => {
    if (!delta) return;
    set((state) => {
      const shouldFinalizeThinking = state.thinkingStartAt != null;
      const duration = computeThinkingDuration(state.thinkingStartAt);
      return {
        thinkingStartAt: shouldFinalizeThinking ? null : state.thinkingStartAt,
        messages: state.messages.map((message) => {
          if (message.id !== state.streamingMessageId) return message;
          if (message.status === "cancelled" || message.status === "error") return message;
          return {
            ...message,
            content: message.content + delta,
            isThinking: shouldFinalizeThinking ? false : message.isThinking,
            thinkingDuration:
              shouldFinalizeThinking && !message.thinkingDuration
                ? duration
                : message.thinkingDuration
          };
        })
      };
    });
  },
  appendThinkingContent: (delta) => {
    if (!delta) return;
    set((state) => ({
      thinkingStartAt: state.thinkingStartAt ?? Date.now(),
      messages: state.messages.map((message) =>
        message.id === state.streamingMessageId &&
        message.status !== "cancelled" &&
        message.status !== "error"
          ? {
              ...message,
              thinking: `${message.thinking ?? ""}${delta}`,
              isThinking: true
            }
          : message
      )
    }));
  },
  submitFeedback: async (messageId, feedback) => {
    const vote = feedback === "like" ? 1 : feedback === "dislike" ? -1 : null;
    const prev = feedbackForMessage(get().messages, messageId);
    set((state) => ({
      messages: withMessageFeedback(state.messages, messageId, feedback)
    }));
    try {
      if (vote === null) {
        await cancelFeedback(messageId);
        toast.success("取消成功");
        return;
      }
      await submitFeedback(messageId, vote);
      toast.success(feedback === "like" ? "点赞成功" : "点踩成功");
    } catch (error) {
      set((state) => ({
        messages: withMessageFeedback(state.messages, messageId, prev)
      }));
      toast.error((error as Error).message || (vote === null ? "取消反馈失败" : "反馈保存失败"));
    }
  },
  toggleSourcesPanel: (messageId) => {
    set((state) => ({
      openedSourceMessageId: state.openedSourceMessageId === messageId ? null : messageId
    }));
  },
  openSourcesPanel: (messageId) => set({ openedSourceMessageId: messageId }),
  closeSourcesPanel: () => set({ openedSourceMessageId: null }),
  loadRecommended: async (messageId) => {
    const target = get().messages.find((message) => message.id === messageId);
    // loading/ready 直接返回：避免同一消息重复请求
    if (!target || target.recommendedState === "loading" || target.recommendedState === "ready") {
      return;
    }
    // 纯手动触发：点击即展开并露出骨架反馈
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId
          ? { ...message, recommendedState: "loading", recommendedOpen: true }
          : message
      ),
      recommendReveal: { id: messageId }
    }));
    try {
      const result = await generateRecommendedQuestions(messageId);
      if (result.status === "FAILED") {
        throw new Error("推荐问题生成失败");
      }
      const list = result.status === "SUCCESS" ? result.questions : [];
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === messageId
            ? { ...message, recommended: list, recommendedState: "ready", recommendedOpen: true }
            : message
        ),
        // 就绪后内容变高，再次请求滚入视口，确保问题不被输入框遮挡
        recommendReveal: { id: messageId }
      }));
    } catch {
      // 失败置 error 态，由面板内「重试」按钮兜底
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === messageId
            ? { ...message, recommendedState: "error", recommendedOpen: true }
            : message
        ),
        recommendReveal: { id: messageId }
      }));
    }
  },
  toggleRecommended: (messageId) => {
    const target = get().messages.find((message) => message.id === messageId);
    if (!target) return;
    // 加载中：保持展开，就绪后原地显示（再次点击不折叠，避免打断）
    if (target.recommendedState === "loading") {
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === messageId ? { ...message, recommendedOpen: true } : message
        ),
        recommendReveal: { id: messageId }
      }));
      return;
    }
    // 已尝试过（成功或失败）：纯展开/收起切换 失败态的重试走面板内按钮
    if (target.recommendedState === "ready" || target.recommendedState === "error") {
      const willOpen = !target.recommendedOpen;
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === messageId
            ? { ...message, recommendedOpen: !message.recommendedOpen }
            : message
        ),
        // 仅在“展开”时滚入视口；收起不滚（保持既有引用避免误触发）
        recommendReveal: willOpen ? { id: messageId } : state.recommendReveal
      }));
      return;
    }
    // idle：手动发起加载 必展开
    void get().loadRecommended(messageId);
  },
  regenerateTurn: async (turnId) => {
    const sessionId = get().currentSessionId;
    if (!sessionId || get().isStreaming || get().isLoading) return;
    const state = get();
    // 找到该轮次的 assistant 消息与原始问题
    const targetIndex = state.messages.findIndex(
      (message) => message.turnId === turnId && message.role === "assistant"
    );
    if (targetIndex < 0) {
      toast.error("未找到可重新生成的回答");
      return;
    }
    const userMsg = [...state.messages]
      .reverse()
      .find((message) => message.turnId === turnId && message.role === "user");
    const question = userMsg?.content?.trim() ?? "";
    if (!question) {
      toast.error("未找到原问题");
      return;
    }
    const deepThinkingEnabled = state.deepThinkingEnabled;
    const knowledgeBaseIds = state.knowledgeBaseIds;
    const inputFocusKey = Date.now();
    const requestId =
      globalThis.crypto?.randomUUID?.() ||
      `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
    const assistantId = `assistant-${Date.now()}`;
    const newAssistant: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      // 与 sendMessage 占位一致：isThinking 只在收到真实 thinking 流后置 true
      thinking: undefined,
      isDeepThinking: deepThinkingEnabled,
      isThinking: false,
      status: "streaming",
      feedback: null,
      agentSteps: [],
      agentExecutionStatus: "running",
      createdAt: new Date().toISOString()
    };
    // 用新的流式占位替换原回答，复用同一消息位置
    set((state) => ({
      messages: state.messages.map((message, index) =>
        index === targetIndex ? newAssistant : message
      ),
      isStreaming: true,
      streamingMessageId: assistantId,
      thinkingStartAt: null,
      inputFocusKey,
      streamTaskId: null,
      cancelRequested: false
    }));

    await runAssistantStream({
      payload: {
        question,
        conversationId: sessionId,
        turnId,
        regenerate: true,
        requestId,
        deepThinking: deepThinkingEnabled ? true : undefined,
        knowledgeBaseIds: knowledgeBaseIds.map(Number)
      },
      assistantId
    });
  }
  };
});
