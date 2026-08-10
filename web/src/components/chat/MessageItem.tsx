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
  /** 是否属于当前最新一轮（驱动 Timeline 展开生命周期：最新轮执行时展开、新轮开始后收起） */
  isLatestTurn?: boolean;
}

export const MessageItem = React.memo(function MessageItem({
  message,
  isLatestTurn = true
}: MessageItemProps) {
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
        agentExecutionSummary: selectedVersion.agentExecutionSummary,
        // mode/terminalState 同样严格绑定版本（老版本缺失时保持 undefined，不做兜底）
        agentExecutionMode: selectedVersion.agentExecutionMode,
        agentTerminalState: selectedVersion.agentTerminalState
      }
    : message;
  const isUser = message.role === "user";
  const showFeedback =
    renderedMessage.role === "assistant" &&
    renderedMessage.status !== "streaming" &&
    (renderedMessage.messageStatus ?? "NORMAL") === "NORMAL" &&
    renderedMessage.id &&
    !renderedMessage.id.startsWith("assistant-");
  // 运行中的「正在深度思考」卡片只在 isThinking 且 thinking 有真实内容时显示；
  // 防御性收紧：即使未来有代码误写 isThinking=true + thinking 为空，也不凭空出现面板
  const isThinking =
    Boolean(renderedMessage.isThinking) &&
    Boolean(renderedMessage.thinking?.trim());
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
  // 仅在 Agent Progress 尚未到达（agentSteps 为空）时才显示传统等待点，
  // 避免 Timeline 已在实时执行时下方还有 loading dots 的信息重复
  const isWaiting =
    renderedMessage.status === "streaming" &&
    !isThinking &&
    !hasContent &&
    !(renderedMessage.agentSteps?.length ?? 0);

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
        {/* 平正文头部：紧凑单行（小头像 + 名称），无整卡边框/阴影/分隔线；AI 身份由 Timeline 的 Sparkles 承担 */}
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--merchant-navy)] text-white">
            <Bot className="h-4 w-4" />
          </span>
          <p className="truncate text-sm font-semibold text-[var(--merchant-text)]">
            邻里鲜选 AI 助手
          </p>
        </div>
        <AgentExecutionTimeline
          steps={renderedMessage.agentSteps}
          status={
            renderedMessage.agentExecutionStatus ??
            (renderedMessage.status === "streaming" ? "running" : "completed")
          }
          summary={renderedMessage.agentExecutionSummary}
          mode={renderedMessage.agentExecutionMode}
          terminalState={renderedMessage.agentTerminalState}
          isCurrentTurn={isLatestTurn}
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
            <p className="text-xs font-medium text-amber-600">该请求无法协助执行</p>
          ) : null}
          {renderedMessage.messageStatus === "ESCALATED" ? (
            <p className="text-xs font-medium text-amber-600">当前资料不足，暂无法可靠确认</p>
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
