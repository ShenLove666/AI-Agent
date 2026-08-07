import { api } from "@/services/api";
import type { AnswerVersion, PersistedMessageStatus, SourceRef } from "@/types";

export interface ConversationVO {
  conversationId: string;
  title: string;
  lastTime?: string;
}

export interface ConversationMessageVO {
  id: number | string;
  conversationId: string;
  role: string;
  content: string;
  thinkingContent?: string | null;
  thinkingDuration?: number | null;
  vote: number | null;
  sources?: SourceRef[] | null;
  recommendedQuestions?: string[] | null;
  recommendedQuestionsStatus?: import("@/types").PersistedRecommendedQuestionStatus | null;
  recommendedQuestionsError?: string | null;
  messageStatus?: PersistedMessageStatus | null;
  createTime?: string;
  turnId?: number | null;
  version?: number | null;
  answerVersions?: AnswerVersion[];
}

export async function listSessions(): Promise<ConversationVO[]> {
  const rows = await api.get<
    unknown,
    Array<{ id: string; title: string; lastTime?: string; updatedAt?: string }>
  >("/conversations");
  return rows.map((row) => ({
    conversationId: row.id,
    title: row.title,
    lastTime: row.lastTime ?? row.updatedAt
  }));
}

export async function deleteSession(conversationId: string) {
  return api.delete(`/conversations/${conversationId}`);
}

export async function renameSession(_conversationId: string, _title: string) {
  return api.patch(`/conversations/${_conversationId}`, { title: _title });
}

export async function listMessages(conversationId: string): Promise<ConversationMessageVO[]> {
  const rows = await api.get<unknown, Array<Record<string, unknown>>>(`/conversations/${conversationId}/messages`);
  return rows.map((row) => {
    let sources: SourceRef[] = [];
    try {
      sources = typeof row.citations === "string" ? JSON.parse(row.citations) : ((row.citations as SourceRef[]) || []);
    } catch { sources = []; }
    return {
      id: row.id as string,
      conversationId,
      role: String(row.role),
      content: String(row.content || ""),
      thinkingContent: (row.thinkingContent as string | null) || null,
      thinkingDuration: (row.thinkingDuration as number | null) || null,
      vote: typeof row.vote === "number" ? row.vote : null,
      sources,
      recommendedQuestions: Array.isArray(row.recommendedQuestions)
        ? (row.recommendedQuestions as string[])
        : null,
      recommendedQuestionsStatus:
        (row.recommendedQuestionsStatus as PersistedMessage["recommendedQuestionsStatus"]) ||
        "NOT_REQUESTED",
      recommendedQuestionsError: (row.recommendedQuestionsError as string | null) || null,
      messageStatus: (row.messageStatus as PersistedMessageStatus) || "NORMAL",
      createTime: row.createdAt as string,
      turnId: typeof row.turnId === "number" ? row.turnId : null,
      version: typeof row.version === "number" ? row.version : null,
      answerVersions: Array.isArray(row.answerVersions)
        ? (row.answerVersions as Array<Record<string, unknown>>).map((version) => ({
            id: String(version.id),
            version: Number(version.version || 1),
            content: String(version.content || ""),
            thinking: (version.thinkingContent as string | null) || undefined,
            thinkingDuration: (version.thinkingDuration as number | null) || undefined,
            feedback: version.vote === 1 ? "like" : version.vote === -1 ? "dislike" : null,
            sources: Array.isArray(version.sources) ? (version.sources as SourceRef[]) : [],
            messageStatus: (version.messageStatus as PersistedMessageStatus) || "NORMAL",
            createdAt: version.createdAt as string
          }))
        : undefined
    };
  });
}
