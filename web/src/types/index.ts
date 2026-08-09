export type Role = "user" | "assistant";

export type FeedbackValue = "like" | "dislike" | null;

export type MessageStatus = "streaming" | "done" | "cancelled" | "error";

export type PersistedMessageStatus = "NORMAL" | "INTERRUPTED" | "REJECTED" | "ERROR";

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
