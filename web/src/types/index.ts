export type Role = "user" | "assistant";

export type FeedbackValue = "like" | "dislike" | null;

export type MessageStatus = "streaming" | "done" | "cancelled" | "error";

export type PersistedMessageStatus = "NORMAL" | "INTERRUPTED" | "REJECTED" | "ERROR";

/** Agent 执行阶段（来自 SSE agent_progress 事件） */
export type AgentProgressPhase =
  | "rewrite"
  | "planning"
  | "tool"
  | "review"
  | "replan"
  | "generation"
  | "complete";

/** Agent 步骤状态 */
export type AgentProgressStatus = "pending" | "running" | "completed" | "warning" | "failed" | "cancelled";

/** Agent 工具调用进度（phase=tool 时携带） */
export interface AgentToolProgress {
  name: string;
  label: string;
  status: AgentProgressStatus;
  argumentsSummary?: string;
  durationMs?: number | null;
  evidenceCount?: number | null;
}

/** SSE agent_progress 事件负载 */
export interface AgentProgressPayload {
  taskId?: string;
  seq: number;
  phase: AgentProgressPhase;
  status: AgentProgressStatus;
  agent?: string;
  plan?: number;
  title: string;
  detail?: string;
  tool?: AgentToolProgress | null;
  metrics?: { evidenceCount?: number; coverage?: number; conflictCount?: number } | null;
  timestamp?: string;
}

/** 时间线中的单步执行记录（stepId 由前端构造，保证 running→completed 原地更新） */
export interface AgentExecutionStep {
  stepId: string;
  seq: number;
  phase: AgentProgressPhase;
  status: AgentProgressStatus;
  plan: number;
  title: string;
  detail?: string;
  tool?: AgentToolProgress | null;
}

/** Agent 执行汇总（finish 时计算；历史消息来自 agent_execution_json） */
export interface AgentExecutionSummary {
  planCount: number;
  toolCallCount: number;
  successfulToolCount?: number;
  evidenceCount: number;
  replanCount: number;
  durationMs?: number;
}

export type AgentExecutionStatus = "running" | "completed" | "failed" | "cancelled";

export interface User {
  userId: string;
  username?: string;
  role: string;
  token: string;
  avatar?: string;
  /** 权限能力集合（settings.write / campaign.confirm / ...），来自 /auth/me */
  permissions?: string[];
  /** 商家数据归属账号 id（组织 owner；无组织时为本人） */
  merchantOwnerId?: number | null;
}

export type CurrentUser = Omit<User, "token">;

export interface Session {
  id: string;
  title: string;
  lastTime?: string;
}

export interface SourceRef {
  index?: number;
  docId?: string;
  docName?: string;
  sourceType?: string;
  fileType?: string | null;
  url?: string | null;
  excerpt?: string;
  provenance?: "observed" | "derived" | "observed+derived" | "synthetic" | string;
}

export interface AnswerVersion {
  id: string;
  version: number;
  content: string;
  thinking?: string;
  thinkingDuration?: number;
  feedback?: FeedbackValue;
  sources?: SourceRef[];
  messageStatus?: PersistedMessageStatus;
  createdAt?: string;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  thinking?: string;
  thinkingDuration?: number;
  isDeepThinking?: boolean;
  isThinking?: boolean;
  createdAt?: string;
  feedback?: FeedbackValue;
  status?: MessageStatus;
  sources?: SourceRef[];
  recommended?: string[];
  recommendedState?: "loading" | "ready" | "error";
  recommendedOpen?: boolean;
  messageStatus?: PersistedMessageStatus;
  turnId?: number;
  version?: number;
  answerVersions?: AnswerVersion[];
  /** Agent 执行时间线步骤（实时 SSE agent_progress 或历史 agent_execution_json 恢复） */
  agentSteps?: AgentExecutionStep[];
  /** Agent 执行整体状态；无 agent_progress 数据的旧消息保持 undefined */
  agentExecutionStatus?: AgentExecutionStatus;
  agentExecutionSummary?: AgentExecutionSummary | null;
}

export type RecommendedQuestionStatus = "SUCCESS" | "EMPTY" | "FAILED";
export type PersistedRecommendedQuestionStatus =
  | "NOT_REQUESTED"
  | "GENERATING"
  | RecommendedQuestionStatus;

export interface RecommendedQuestionsPayload {
  status: RecommendedQuestionStatus;
  questions: string[];
}

export interface StreamMetaPayload {
  conversationId: string;
  taskId: string;
  title?: string | null;
  turnId?: number | null;
  userMessageId?: string | number | null;
}

export interface MessageDeltaPayload {
  type: string;
  delta: string;
}

export interface CompletionPayload {
  messageId?: string | null;
  title?: string | null;
  sources?: SourceRef[];
  messageStatus?: PersistedMessageStatus;
  turnId?: number | null;
  userMessageId?: string | number | null;
  version?: number | null;
}
