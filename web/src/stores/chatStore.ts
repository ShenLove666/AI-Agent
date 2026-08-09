import { create } from "zustand";
import { toast } from "sonner";

import type {
  AgentExecutionStep,
  AgentExecutionSummary,
  AgentProgressPayload,
  AgentProgressPhase,
  AgentProgressStatus,
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
import { storage } from "@/utils/storage";

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
  if (status === "ERROR" || status === "REJECTED") return "error";
  return "done";
}

const AGENT_PROGRESS_PHASES: AgentProgressPhase[] = [
  "rewrite",
  "planning",
  "tool",
  "review",
  "replan",
  "generation",
  "complete"
];

const AGENT_PROGRESS_STATUSES: AgentProgressStatus[] = [
  "pending",
  "running",
  "completed",
  "warning",
  "failed",
  "cancelled"
];

function isAgentProgressPhase(value: unknown): value is AgentProgressPhase {
  return typeof value === "string" && (AGENT_PROGRESS_PHASES as string[]).includes(value);
}

function isAgentProgressStatus(value: unknown): value is AgentProgressStatus {
  return typeof value === "string" && (AGENT_PROGRESS_STATUSES as string[]).includes(value);
}

/**
 * 构造稳定 stepId：`plan-${plan}-${phase}-${toolName}-${occurrence}`，
 * occurrence 为该 plan+phase+tool 组合在已有步骤中出现的次数。
 * running→completed 的同一逻辑步骤得到相同 stepId，可原地更新。
 */
function buildAgentStepId(payload: AgentProgressPayload, steps: AgentExecutionStep[]): string {
  const plan = payload.plan ?? 1;
  const toolName = payload.tool?.name ?? "";
  const key = `${plan}|${payload.phase}|${toolName}`;
  const keyOf = (step: AgentExecutionStep) =>
    `${step.plan}|${step.phase}|${step.tool?.name ?? ""}`;
  // 同 key 步骤已存在时复用其 stepId（running→completed 原地更新），
  // 否则按已出现次数 +1 编号（同一 plan 内同工具多次调用仍可区分）
  const sameKey = steps.filter((step) => keyOf(step) === key);
  if (sameKey.length > 0) return sameKey[0].stepId;
  return `plan-${plan}-${payload.phase}-${toolName}-${sameKey.length + 1}`;
}

/** finish 时计算汇总：tool 步骤完成/失败数、工具证据之和、replan 数、最大 plan 编号 */
function computeAgentExecutionSummary(steps?: AgentExecutionStep[]): AgentExecutionSummary | null {
  if (!steps || steps.length === 0) return null;
  const toolSteps = steps.filter((step) => step.phase === "tool" && step.tool);
  const toolCallCount = toolSteps.filter(
    (step) => step.status === "completed" || step.status === "failed"
  ).length;
  const evidenceCount = toolSteps.reduce(
    (sum, step) => sum + (step.tool?.status === "completed" ? step.tool.evidenceCount ?? 0 : 0),
    0
  );
  const replanCount = steps.filter((step) => step.phase === "replan").length;
  const planCount = steps.reduce((max, step) => Math.max(max, step.plan), 1);
  return { planCount, toolCallCount, evidenceCount, replanCount };
}

function cancelAgentSteps(steps?: AgentExecutionStep[]): AgentExecutionStep[] | undefined {
  if (!steps) return steps;
  return steps.map((step) =>
    step.status === "running" ? { ...step, status: "cancelled" as const } : step
  );
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

function toNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/**
 * 从后端持久化的 agent_execution_json（字符串或已解析对象）恢复时间线。
 * 字段缺失/null/解析失败一律忽略，返回空对象（优雅降级）。
 */
function restoreAgentExecution(
  json?: unknown
): Pick<Message, "agentSteps" | "agentExecutionStatus" | "agentExecutionSummary"> {
  if (!json || typeof json !== "object") return {};
  const raw = json as Record<string, unknown>;
  if (!Array.isArray(raw.steps)) return {};
  const steps: AgentExecutionStep[] = [];
  let maxPlan = 1;
  for (const item of raw.steps) {
    if (!item || typeof item !== "object") continue;
    const step = item as Record<string, unknown>;
    const plan = (() => {
      const value = toNumber(step.plan, 1);
      return value > 0 ? value : 1;
    })();
    const phase = isAgentProgressPhase(step.phase) ? step.phase : "tool";
    const status = isAgentProgressStatus(step.status) ? step.status : "completed";
    const seq = toNumber(step.seq, steps.length);
    const rawTool = step.tool as Record<string, unknown> | null | undefined;
    const toolLabel = typeof step.toolLabel === "string" ? step.toolLabel : "";
    const tool: AgentExecutionStep["tool"] =
      rawTool && typeof rawTool === "object" && typeof rawTool.name === "string"
        ? {
            name: String(rawTool.name),
            label: typeof rawTool.label === "string" ? rawTool.label : String(rawTool.name),
            status: isAgentProgressStatus(rawTool.status) ? rawTool.status : "completed",
            argumentsSummary:
              typeof rawTool.argumentsSummary === "string"
                ? rawTool.argumentsSummary
                : undefined,
            durationMs:
              typeof rawTool.durationMs === "number" ? rawTool.durationMs : undefined,
            evidenceCount:
              typeof rawTool.evidenceCount === "number" ? rawTool.evidenceCount : undefined
          }
        : toolLabel
          ? { name: toolLabel, label: toolLabel, status: "completed" as const }
          : undefined;
    const stepId =
      typeof step.stepId === "string" && step.stepId
        ? step.stepId
        : `plan-${plan}-${phase}-${tool?.name ?? ""}-${seq}`;
    steps.push({
      stepId,
      seq,
      phase,
      status,
      plan,
      title: String(step.title ?? ""),
      detail: typeof step.detail === "string" ? step.detail : undefined,
      tool
    });
    if (plan > maxPlan) maxPlan = plan;
  }
  steps.sort((a, b) => a.seq - b.seq);
  if (steps.length === 0) return {};
  const summaryRaw = raw.summary as Record<string, unknown> | null | undefined;
  const summary: AgentExecutionSummary =
    summaryRaw && typeof summaryRaw === "object"
      ? {
          planCount: toNumber(summaryRaw.planCount, maxPlan),
          toolCallCount: toNumber(summaryRaw.toolCallCount, 0),
          evidenceCount: toNumber(summaryRaw.evidenceCount, 0),
          replanCount: toNumber(summaryRaw.replanCount, 0),
          durationMs: typeof summaryRaw.durationMs === "number" ? summaryRaw.durationMs : undefined
        }
      : computeAgentExecutionSummary(steps) ?? {
          planCount: maxPlan,
          toolCallCount: 0,
          evidenceCount: 0,
          replanCount: 0
        };
  return { agentSteps: steps, agentExecutionStatus: "completed", agentExecutionSummary: summary };
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
    // 老消息无 agent_execution_json 时保持 undefined，页面正常降级
    ...restoreAgentExecution(item.agentExecutionJson)
  }));
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export const useChatStore = create<ChatState>((set, get) => {
  /**
   * 应用单条 agent_progress 事件到当前流式消息。
   * - 仅更新 streamingMessageId 对应的 assistant 消息（老请求不污染新请求）
   * - seq 全局递增去重
   * - stepId 由前端构造，running→completed 原地更新
   * - phase=complete 只是收尾标记，不进入时间线（finish 事件负责收尾）
   */
  const handleAgentProgress = (payload: AgentProgressPayload) => {
    const { streamingMessageId } = get();
    if (!streamingMessageId) return;
    const target = get().messages.find((message) => message.id === streamingMessageId);
    // 消息已被替换（会话切换/重新加载）或已结束（取消/失败）时忽略后续事件
    if (!target || target.role !== "assistant") return;
    if (target.agentExecutionStatus !== "running") return;
    const steps = target.agentSteps ?? [];
    if (steps.some((step) => step.seq === payload.seq)) return;
    if (payload.phase === "complete") return;
    const stepId = buildAgentStepId(payload, steps);
    const existingIndex = steps.findIndex((step) => step.stepId === stepId);
    const nextStep: AgentExecutionStep = {
      stepId,
      seq: payload.seq,
      phase: payload.phase,
      status: payload.status,
      plan: payload.plan ?? 1,
      title: payload.title,
      detail: payload.detail,
      tool: payload.tool ?? undefined
    };
    const nextSteps =
      existingIndex >= 0
        ? steps.map((step, index) => (index === existingIndex ? { ...step, ...nextStep } : step))
        : [...steps, nextStep];
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === state.streamingMessageId
          ? { ...message, agentSteps: nextSteps }
          : message
      )
    }));
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
                  agentExecutionSummary: computeAgentExecutionSummary(message.agentSteps)
                }
              : message
          )
        }));
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
    try {
      await deleteSessionRequest(sessionId);
      set((state) => ({
        sessions: state.sessions.filter((session) => session.id !== sessionId),
        messages: state.currentSessionId === sessionId ? [] : state.messages,
        currentSessionId: state.currentSessionId === sessionId ? null : state.currentSessionId,
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
    try {
      const data = await listMessages(sessionId);
      if (get().currentSessionId !== sessionId) {
        return;
      }
      const mapped = mapConversationMessages(data);
      set({ messages: mapped });
    } catch (error) {
      toast.error((error as Error).message || "加载消息失败");
    } finally {
      if (get().currentSessionId !== sessionId) {
        set({ isLoading: false });
        return;
      }
      set({
        isLoading: false,
        isStreaming: false,
        streamTaskId: null,
        streamAbort: null,
        streamingMessageId: null,
        cancelRequested: false
      });
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
      thinking: deepThinkingEnabled ? "" : undefined,
      isDeepThinking: deepThinkingEnabled,
      isThinking: deepThinkingEnabled,
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
    const { isStreaming, streamTaskId, streamingMessageId } = get();
    if (!isStreaming) return;
    set({ cancelRequested: true });
    if (streamingMessageId) {
      // 用户主动停止：进行中的步骤标记 cancelled，后续 agent_progress 事件被忽略
      set((state) => ({
        messages: state.messages.map((message) =>
          message.id === streamingMessageId
            ? {
                ...message,
                agentSteps: cancelAgentSteps(message.agentSteps),
                agentExecutionStatus: "cancelled"
              }
            : message
        )
      }));
    }
    if (streamTaskId) {
      stopTask(streamTaskId).catch(() => null);
    }
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
      thinking: deepThinkingEnabled ? "" : undefined,
      isDeepThinking: deepThinkingEnabled,
      isThinking: deepThinkingEnabled,
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
