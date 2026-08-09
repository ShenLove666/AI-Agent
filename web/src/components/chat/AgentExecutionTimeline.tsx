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
  AgentExecutionSummary,
  AgentToolProgress
} from "@/types";

interface AgentExecutionTimelineProps {
  steps?: AgentExecutionStep[];
  status?: AgentExecutionStatus;
  summary?: AgentExecutionSummary | null;
  className?: string;
  /** 挂载时是否展开；默认 running 展开、其余折叠（历史消息默认折叠） */
  initialExpanded?: boolean;
}

function StepStatusIcon({ step }: { step: AgentExecutionStep }) {
  if (step.phase === "replan") {
    return <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />;
  }
  switch (step.status) {
    case "completed":
      return <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />;
    case "running":
      return <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-indigo-500" />;
    case "warning":
      return <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />;
    case "failed":
      return <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />;
    case "cancelled":
      return <Square className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />;
    default:
      return <Circle className="mt-0.5 h-4 w-4 shrink-0 text-slate-300" />;
  }
}

function ToolCallLine({ tool }: { tool: AgentToolProgress }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1.5">
      <span className="text-xs font-medium text-slate-600">{tool.label}</span>
      {tool.argumentsSummary ? (
        <span className="truncate text-[11px] text-slate-400">{tool.argumentsSummary}</span>
      ) : null}
      <span className="ml-auto flex shrink-0 items-center gap-2 text-[11px] text-slate-400">
        {typeof tool.durationMs === "number" ? <span>{tool.durationMs}ms</span> : null}
        {typeof tool.evidenceCount === "number" ? (
          <span>{tool.evidenceCount} 条证据</span>
        ) : null}
      </span>
    </div>
  );
}

export function AgentExecutionTimeline({
  steps,
  status = "completed",
  summary,
  className,
  initialExpanded
}: AgentExecutionTimelineProps) {
  const isRunning = status === "running";
  // hooks 必须在条件返回之前全部执行，保证渲染顺序稳定
  const [expanded, setExpanded] = React.useState(() => initialExpanded ?? isRunning);
  const prevStatusRef = React.useRef(status);
  const bodyId = React.useId();

  // 执行中 → 完成/失败/取消时自动折叠为摘要行
  React.useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    if (prev === "running" && status !== "running") {
      setExpanded(false);
    }
  }, [status]);

  const stepsList = steps ?? [];
  // 空 steps（旧消息/旧后端无 agent_progress）时不渲染任何内容
  if (stepsList.length === 0) return null;

  const runningSteps = stepsList.filter((step) => step.status === "running");
  const lastRunning = runningSteps.length > 0 ? runningSteps[runningSteps.length - 1] : undefined;

  const planGroups: Array<{ plan: number; steps: AgentExecutionStep[] }> = [];
  {
    const groups = new Map<number, AgentExecutionStep[]>();
    for (const step of stepsList) {
      const list = groups.get(step.plan);
      if (list) {
        list.push(step);
      } else {
        groups.set(step.plan, [step]);
      }
    }
    for (const [plan, list] of groups.entries()) {
      planGroups.push({
        plan,
        steps: [...list].sort((a, b) => a.seq - b.seq)
      });
    }
    planGroups.sort((a, b) => a.plan - b.plan);
  }
  const showPlanTitles = planGroups.length > 1;

  const summaryText = (() => {
    if (isRunning) return "正在执行 Agent 分析…";
    if (status === "failed") return "处理失败";
    if (status === "cancelled") return "已停止处理";
    if (summary) {
      const parts = ["已完成 Agent 分析"];
      if (summary.toolCallCount > 0) parts.push(`${summary.toolCallCount} 次查询`);
      if (summary.evidenceCount > 0) parts.push(`${summary.evidenceCount} 条证据`);
      return parts.join(" · ");
    }
    return "已完成 Agent 分析";
  })();

  const collapsedIcon = isRunning ? (
    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-500" />
  ) : status === "failed" ? (
    <XCircle className="h-4 w-4 shrink-0 text-rose-500" />
  ) : status === "cancelled" ? (
    <Square className="h-4 w-4 shrink-0 text-slate-400" />
  ) : (
    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
  );

  return (
    <section
      aria-label="Agent 执行过程"
      className={cn(
        "overflow-hidden rounded-xl border border-indigo-100 bg-indigo-50/50",
        className
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={bodyId}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-indigo-100/40"
      >
        {expanded ? (
          <>
            <span className="flex min-w-0 flex-1 items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 shrink-0 text-indigo-500" />
              <span className="text-[13px] font-semibold text-slate-700">Agent 执行过程</span>
            </span>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-indigo-100 bg-white px-2 py-0.5 text-[11px] font-medium text-indigo-600">
              <Sparkles className="h-3 w-3" />
              AI
            </span>
          </>
        ) : (
          <>
            {collapsedIcon}
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700">
              {summaryText}
            </span>
            <span className="shrink-0 text-xs font-medium text-indigo-600">查看执行过程</span>
          </>
        )}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-indigo-400 transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>
      {expanded ? (
        <div id={bodyId} className="px-3 pb-3">
          {isRunning ? (
            <div className="mt-1 flex items-start gap-2 rounded-lg border border-indigo-100 bg-white px-3 py-2.5">
              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-indigo-500" />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-indigo-700">
                  {lastRunning
                    ? `${lastRunning.title.replace(/[。.…\s]+$/, "")}…`
                    : "正在分析问题…"}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">Agent 正在调用业务工具并核验证据</p>
              </div>
            </div>
          ) : null}
          <div className="mt-2.5 space-y-2.5">
            {planGroups.map(({ plan, steps: planSteps }) => (
              <div key={plan}>
                {showPlanTitles ? (
                  <p className="mb-1.5 text-[11px] font-medium tracking-wide text-slate-400">
                    计划 {plan}
                  </p>
                ) : null}
                <ul className="space-y-1.5">
                  {planSteps.map((step) => (
                    <li
                      key={step.stepId}
                      data-status={step.status}
                      className="rounded-lg border border-indigo-100 bg-white px-3 py-2.5"
                    >
                      <div className="flex items-start gap-2.5">
                        <StepStatusIcon step={step} />
                        <div className="min-w-0 flex-1">
                          <p
                            className={cn(
                              "text-[13px] leading-relaxed",
                              step.status === "completed"
                                ? "text-slate-600"
                                : "font-medium text-slate-700"
                            )}
                          >
                            {step.title}
                          </p>
                          {step.detail ? (
                            <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                              {step.detail}
                            </p>
                          ) : null}
                          {step.tool ? <ToolCallLine tool={step.tool} /> : null}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
