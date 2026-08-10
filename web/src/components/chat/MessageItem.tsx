import * as React from "react";
import { Bot, Brain, ChevronDown, ChevronLeft, ChevronRight, RotateCcw, Sparkles } from "lucide-react";

import { AgentExecutionTimeline } from "@/components/chat/AgentExecutionTimeline";
import { FeedbackButtons } from "@/components/chat/FeedbackButtons";
import { MarkdownRenderer } from "@/components/chat/MarkdownRenderer";
import { RecommendedQuestions } from "@/components/chat/RecommendedQuestions";
import { RecommendedQuestionsButton } from "@/components/chat/RecommendedQuestionsButton";
import { SourcesButton } from "@/components/chat/SourcesButton";
import { ThinkingIndicator } from "@/components/chat/ThinkingIndicator";
import { cn } from "@/lib/utils";
import type { Message } from "@/types";
import { useChatStore } from "@/stores/chatStore";

interface MessageItemProps {
  message: Message;
}

export const MessageItem = React.memo(function MessageItem({ message }: MessageItemProps) {
  const regenerateTurn = useChatStore((state) => state.regenerateTurn);
  const isLoading = useChatStore((state) => state.isLoading);
  const versions = message.answerVersions ?? [];
  const activeVersionIndex = Math.max(
    0,
    versions.findIndex((item) => item.version === message.version)
  );
  const [versionIndex, setVersionIndex] = React.useState(activeVersionIndex);
  React.useEffect(() => {
    setVersionIndex(activeVersionIndex);
  }, [activeVersionIndex, versions.length]);
  const selectedVersion = versions[versionIndex];
  const renderedMessage: Message = selectedVersion
    ? {
        ...message,
        id: selectedVersion.id,
        version: selectedVersion.version,
        content: selectedVersion.content,
        thinking: selectedVersion.thinking,
        thinkingDuration: selectedVersion.thinkingDuration,
        feedback: selectedVersion.feedback,
        sources: selectedVersion.sources,
        messageStatus: selectedVersion.messageStatus,
        // 版本切换时严格使用该版本持久化的 Agent 执行记录，Timeline 随版本展示；
        // 不做 ?? message.* 兜底：老版本无 Timeline 数据时若回退到 message，
        // 会把当前版本的执行过程串显示到旧版本上
        agentSteps: selectedVersion.agentSteps,
        agentExecutionStatus: selectedVersion.agentExecutionStatus,
        agentExecutionSummary: selectedVersion.agentExecutionSummary
      }
    : message;
  const isUser = message.role === "user";
  const showFeedback =
    renderedMessage.role === "assistant" &&
    renderedMessage.status !== "streaming" &&
    (renderedMessage.messageStatus ?? "NORMAL") === "NORMAL" &&
    renderedMessage.id &&
    !renderedMessage.id.startsWith("assistant-");
  const isThinking = Boolean(renderedMessage.isThinking);
  const hasSources =
    renderedMessage.role === "assistant" &&
    renderedMessage.status !== "streaming" &&
    (renderedMessage.sources?.length ?? 0) > 0;
  // 推荐追问：完成态且已落库的助手消息（真实 messageId）方可触发 与反馈按钮判据一致
  const canRecommend =
    renderedMessage.role === "assistant" &&
    renderedMessage.status !== "streaming" &&
    Boolean(renderedMessage.id) &&
    (renderedMessage.messageStatus ?? "NORMAL") === "NORMAL" &&
    !renderedMessage.id.startsWith("assistant-");
  const [thinkingExpanded, setThinkingExpanded] = React.useState(false);
  const hasThinking = Boolean(renderedMessage.thinking && renderedMessage.thinking.trim().length > 0);
  const hasContent = renderedMessage.content.trim().length > 0;
  const isWaiting = renderedMessage.status === "streaming" && !isThinking && !hasContent;

  if (isUser) {
    return (
      <div className="flex">
        <div className="user-message">
          <p className="whitespace-pre-wrap break-words">{renderedMessage.content}</p>
        </div>
      </div>
    );
  }

  const thinkingDuration = renderedMessage.thinkingDuration ? `${renderedMessage.thinkingDuration}秒` : "";
  return (
    <div className="group flex">
      <div className="min-w-0 flex-1 space-y-3">
        {/* 平正文头部：紧凑单行（小头像 + 名称 + 内联 AI 徽标），无整卡边框/阴影/分隔线 */}
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--merchant-navy)] text-white">
            <Bot className="h-4 w-4" />
          </span>
          <p className="truncate text-sm font-semibold text-[var(--merchant-text)]">
            邻里售后助手
          </p>
          <span className="hidden items-center gap-1 rounded-full border border-[var(--merchant-cyan-border)] bg-[var(--merchant-cyan-soft)] px-2 py-0.5 text-[11px] font-medium text-[var(--merchant-cyan-strong)] sm:inline-flex">
            <Sparkles className="h-3 w-3" />
            AI 辅助
          </span>
        </div>
        <AgentExecutionTimeline
          steps={renderedMessage.agentSteps}
          status={
            renderedMessage.agentExecutionStatus ??
            (renderedMessage.status === "streaming" ? "running" : "completed")
          }
          summary={renderedMessage.agentExecutionSummary}
          initialExpanded={renderedMessage.status === "streaming"}
        />
        {isThinking ? (
          <ThinkingIndicator content={renderedMessage.thinking} duration={renderedMessage.thinkingDuration} />
        ) : null}
        {!isThinking && hasThinking ? (
          <div className="overflow-hidden rounded-lg border border-[#BFDBFE] bg-[#DBEAFE]">
            <button
              type="button"
              onClick={() => setThinkingExpanded((prev) => !prev)}
              className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-[#BFDBFE]/30"
            >
              <div className="flex flex-1 items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#BFDBFE]">
                  <Brain className="h-4 w-4 text-[#2563EB]" />
                </div>
                <span className="text-sm font-medium text-[#2563EB]">深度思考</span>
                {thinkingDuration ? (
                  <span className="rounded-full bg-[#BFDBFE] px-2 py-0.5 text-xs text-[#2563EB]">
                    {thinkingDuration}
                  </span>
                ) : null}
              </div>
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-[#3B82F6] transition-transform",
                  thinkingExpanded && "rotate-180"
                )}
              />
            </button>
            {thinkingExpanded ? (
              <div className="border-t border-[#BFDBFE] px-4 pb-4">
                <div className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[#1E40AF]">
                  {renderedMessage.thinking}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
        <div className="space-y-2">
          {isWaiting ? (
            <div className="ai-wait" aria-label="思考中">
              <span className="ai-wait-dots" aria-hidden="true">
                <span className="ai-wait-dot" />
                <span className="ai-wait-dot" />
                <span className="ai-wait-dot" />
              </span>
            </div>
          ) : null}
          {hasContent ? (
            <MarkdownRenderer
              content={renderedMessage.content}
              messageId={renderedMessage.id}
              sources={renderedMessage.sources}
            />
          ) : null}
          {renderedMessage.messageStatus === "INTERRUPTED" ? (
            <p className="text-xs font-medium text-amber-600">已停止生成</p>
          ) : null}
          {renderedMessage.messageStatus === "ERROR" ? (
            <p className="text-xs font-medium text-rose-500">生成失败</p>
          ) : null}
          {renderedMessage.messageStatus === "REJECTED" ? (
            <p className="text-xs font-medium text-rose-500">请求被拒绝</p>
          ) : null}
          {showFeedback || hasSources || canRecommend || Boolean(message.turnId) ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-[#edf1f3] pt-3">
              {showFeedback ? (
                <FeedbackButtons
                  messageId={renderedMessage.id}
                  feedback={renderedMessage.feedback ?? null}
                  content={renderedMessage.content}
                  alwaysVisible
                />
              ) : null}
              {hasSources ? (
                <SourcesButton messageId={renderedMessage.id} sources={renderedMessage.sources!} />
              ) : null}
              {canRecommend ? <RecommendedQuestionsButton message={renderedMessage} /> : null}
              {versions.length > 1 ? (
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <button type="button" aria-label="上一版答案" disabled={versionIndex === 0} onClick={() => setVersionIndex((value) => Math.max(0, value - 1))} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft className="h-3.5 w-3.5" /></button>
                  <span>{versionIndex + 1} / {versions.length}</span>
                  <button type="button" aria-label="下一版答案" disabled={versionIndex === versions.length - 1} onClick={() => setVersionIndex((value) => Math.min(versions.length - 1, value + 1))} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronRight className="h-3.5 w-3.5" /></button>
                </div>
              ) : null}
              {message.turnId && message.status !== "streaming" ? (
                <button type="button" disabled={isLoading} onClick={() => void regenerateTurn(message.turnId!)} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40" title="重新生成"><RotateCcw className="h-4 w-4" /></button>
              ) : null}
            </div>
          ) : null}
          {canRecommend ? <RecommendedQuestions message={renderedMessage} /> : null}
        </div>
      </div>
    </div>
  );
});
