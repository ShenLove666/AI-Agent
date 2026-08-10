import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Circle,
  Loader2,
  RefreshCw,
  Sparkles,
  Square,
  XCircle
} from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  AgentExecutionStatus,
  AgentExecutionStep,
  AgentExecutionSummary
} from "@/types";
import { buildAgentTimelineViewModel } from "@/utils/agentTimelineViewModel";
import type { TimelineRow } from "@/utils/agentTimelineViewModel";

interface AgentExecutionTimelineProps {
  steps?: AgentExecutionStep[];
  status?: AgentExecutionStatus;
  summary?: AgentExecutionSummary | null;
  className?: string;
  /**
   * 是否属于当前最新一轮：最新轮执行时展开并保持展开（完成后不自动折叠），
   * 不再是最新轮（用户发送了下一问）时收起；历史会话加载默认折叠。
   */
  isCurrentTurn?: boolean;
}

/** 行节点图标：replan 用琥珀色刷新图标，其余按状态着色（running 为青色旋转环） */
function RowIcon({ row }: { row: TimelineRow }) {
  const base = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border";
  if (row.kind === "replan") {
    return (
      <span className={cn(base, "border-amber-200 bg-amber-50 text-amber-500")}>
        <RefreshCw className="h-3 w-3" />
      </span>
    );
  }
  switch (row.status) {
    case "running":
      return (
        <span className={cn(base, "border-cyan-200 bg-cyan-50 text-cyan-600")}>
          <Loader2 className="h-3 w-3 animate-spin" />
        </span>
      );
    case "completed":
      return (
        <span className={cn(base, "border-emerald-200 bg-emerald-50 text-emerald-600")}>
          <CheckCircle2 className="h-3 w-3" />
        </span>
      );
    case "warning":
      return (
        <span className={cn(base, "border-amber-200 bg-amber-50 text-amber-500")}>
          <AlertCircle className="h-3 w-3" />
        </span>
      );
    case "failed":
      return (
        <span className={cn(base, "border-rose-200 bg-rose-50 text-rose-500")}>
          <XCircle className="h-3 w-3" />
        </span>
      );
    case "cancelled":
      return (
        <span className={cn(base, "border-slate-200 bg-slate-100 text-slate-400")}>
          <Square className="h-3 w-3" />
        </span>
      );
    default:
      return (
        <span className={cn(base, "border-slate-200 bg-slate-50 text-slate-300")}>
          <Circle className="h-3 w-3" />
        </span>
      );
  }
}

/** 时间线单行：节点 + 连接线轨道 + 内容（flat 拍平，无内部滚动容器） */
function TimelineRowView({
  row,
  isLast,
  onExpandRound
}: {
  row: TimelineRow;
  isLast: boolean;
  onExpandRound: (roundIndex: number) => void;
}) {
  return (
    <li data-status={row.status} className="relative flex gap-2.5">
      {/* 节点 + 连接线轨道 */}
      <div className="flex w-5 shrink-0 flex-col items-center">
        <span className="mt-0.5">
          <RowIcon row={row} />
        </span>
        {isLast ? (
          <span className="flex-1" />
        ) : (
          <span className="my-0.5 w-px flex-1 bg-slate-200" />
        )}
      </div>
      {/* 内容 */}
      <div className={cn("min-w-0 flex-1", isLast ? "pb-1" : "pb-3")}>
        {row.kind === "round-summary" ? (
          <div className="flex items-center gap-2 pt-0.5">
            <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-slate-600">
              {row.title}
            </p>
            <button
              type="button"
              onClick={() => onExpandRound(row.roundIndex)}
              className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-500 transition-colors hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-600"
            >
              查看详情
            </button>
          </div>
        ) : (
          <div className="flex items-baseline gap-2 pt-0.5">
            <p
              className={cn(
                "min-w-0 flex-1 text-[13px] leading-relaxed",
                row.status === "completed" || row.status === "cancelled"
                  ? "text-slate-600"
                  : "font-medium text-slate-700"
              )}
            >
              {row.title}
            </p>
            {row.tool && typeof row.tool.durationMs === "number" ? (
              <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
                {row.tool.durationMs}ms
              </span>
            ) : null}
          </div>
        )}
        {row.detail ? (
          <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{row.detail}</p>
        ) : null}
      </div>
    </li>
  );
}

export function AgentExecutionTimeline({
  steps,
  status = "completed",
  summary,
  className,
  isCurrentTurn = true
}: AgentExecutionTimelineProps) {
  const isRunning = status === "running";
  // hooks 必须在条件返回之前全部执行，保证渲染顺序稳定
  // 展开生命周期：最新轮执行时展开；完成后保持展开（不自动折叠，避免高度骤减）；
  // 用户发送下一问（isCurrentTurn → false）后收起；历史会话加载默认折叠
  const [expanded, setExpanded] = React.useState(() => isCurrentTurn && isRunning);
  const prevIsCurrentTurnRef = React.useRef(isCurrentTurn);
  const bodyId = React.useId();
  // 用户点「查看详情」展开的旧轮（roundIndex 集合，驱动 ViewModel 的 expandedRounds）
  const [expandedRounds, setExpandedRounds] = React.useState<Set<number>>(new Set());

  React.useEffect(() => {
    const prevTurn = prevIsCurrentTurnRef.current;
    prevIsCurrentTurnRef.current = isCurrentTurn;
    if (isCurrentTurn && !prevTurn) {
      setExpanded(true);
    } else if (!isCurrentTurn && prevTurn) {
      setExpanded(false);
    }
  }, [isCurrentTurn]);

  const stepsList = steps ?? [];
  // 空 steps（旧消息/旧后端无进度事件）时不渲染任何内容
  if (stepsList.length === 0) return null;

  const vm = buildAgentTimelineViewModel(stepsList, { status, summary, expandedRounds });

  const handleExpandRound = (roundIndex: number) => {
    setExpandedRounds((prev) => {
      if (prev.has(roundIndex)) return prev;
      const next = new Set(prev);
      next.add(roundIndex);
      return next;
    });
  };

  const collapsedIcon = isRunning ? (
    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-cyan-600" />
  ) : status === "failed" ? (
    <XCircle className="h-4 w-4 shrink-0 text-rose-500" />
  ) : status === "cancelled" ? (
    <Square className="h-4 w-4 shrink-0 text-slate-400" />
  ) : (
    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
  );

  return (
    <section
      aria-label="AI 处理过程"
      className={cn("rounded-lg border border-slate-200 bg-white", className)}
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={bodyId}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-slate-50"
      >
        {expanded ? (
          <>
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
            <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-700">
              {vm.currentActivityTitle ?? "AI 处理过程"}
            </span>
          </>
        ) : (
          <>
            {collapsedIcon}
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700">
              {vm.summaryText}
            </span>
            <span className="shrink-0 text-xs font-medium text-indigo-600">查看处理过程</span>
          </>
        )}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>
      {expanded ? (
        <div id={bodyId} className="px-3 pb-3">
          {/* 拍平行列表：无内部滚动容器，页面只保留 Virtuoso 一个滚动权威 */}
          <ol className="mt-2.5">
            {vm.rows.map((row, index) => (
              <TimelineRowView
                key={row.key}
                row={row}
                isLast={index === vm.rows.length - 1}
                onExpandRound={handleExpandRound}
              />
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
