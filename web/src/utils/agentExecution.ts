import type {
  AgentExecutionStatus,
  AgentExecutionStep,
  AgentExecutionSummary,
  AgentProgressPhase,
  AgentProgressStatus,
  AgentTerminalState,
  Message,
  PersistedMessageStatus
} from "@/types";

/**
 * Agent 执行时间线工具函数（restore / 汇总 / 取消）。
 * 仅 import type，避免与 chatStore 等模块产生运行时循环依赖。
 */

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

export function isAgentProgressPhase(value: unknown): value is AgentProgressPhase {
  return typeof value === "string" && (AGENT_PROGRESS_PHASES as string[]).includes(value);
}

export function isAgentProgressStatus(value: unknown): value is AgentProgressStatus {
  return typeof value === "string" && (AGENT_PROGRESS_STATUSES as string[]).includes(value);
}

const AGENT_TERMINAL_STATES: AgentTerminalState[] = [
  "direct",
  "grounded",
  "refused",
  "escalated"
];

function isAgentTerminalState(value: unknown): value is AgentTerminalState {
  return typeof value === "string" && (AGENT_TERMINAL_STATES as string[]).includes(value);
}

export function toNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** finish 时计算汇总：tool 步骤完成/失败数、工具证据之和、replan 数、最大 plan 编号 */
export function computeAgentExecutionSummary(
  steps?: AgentExecutionStep[]
): AgentExecutionSummary | null {
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

/** 把仍为 running 的步骤 finalize 为指定状态（cancelled/failed/completed） */
export function finalizeRunningSteps(
  steps: AgentExecutionStep[],
  status: AgentProgressStatus
): AgentExecutionStep[] {
  return steps.map((step) => (step.status === "running" ? { ...step, status } : step));
}

/** 取消时把仍为 running 的步骤标记为 cancelled */
export function cancelAgentSteps(steps?: AgentExecutionStep[]): AgentExecutionStep[] | undefined {
  if (!steps) return steps;
  return finalizeRunningSteps(steps, "cancelled");
}

/**
 * 由持久化 messageStatus 推导整体执行状态：
 * INTERRUPTED → cancelled；ERROR → failed；
 * REJECTED/ESCALATED（受限结果，非失败）→ completed；其余 → completed。
 * 受限消息的 Timeline 文案由 mode/terminalState 驱动（refused/escalated
 * 显示固定用户文案），整体状态仅用于 restore 无 terminalState 的旧数据。
 */
export function deriveAgentExecutionStatus(
  messageStatus?: PersistedMessageStatus | null
): AgentExecutionStatus {
  if (messageStatus === "INTERRUPTED") return "cancelled";
  if (messageStatus === "ERROR") return "failed";
  return "completed";
}

/**
 * 从后端持久化的 agent_execution_json（字符串或已解析对象）恢复时间线。
 * 字段缺失/null/解析失败一律忽略，返回空对象（优雅降级）。
 *
 * 持久化步骤已按 (plan,phase,toolKey) 合并为最终态，tool 步骤只有
 * {label, toolKey}（无 name），此处会回退恢复出工具行。
 */
export function restoreAgentExecution(
  json?: unknown,
  messageStatus?: PersistedMessageStatus | null
): Pick<
  Message,
  | "agentSteps"
  | "agentExecutionStatus"
  | "agentExecutionSummary"
  | "agentExecutionMode"
  | "agentTerminalState"
> {
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
      rawTool && typeof rawTool === "object"
        ? {
            // 持久化数据只有 {label, toolKey}（无 name）：依次回退，保证工具行可恢复
            name:
              typeof rawTool.name === "string"
                ? rawTool.name
                : typeof rawTool.toolKey === "string"
                  ? rawTool.toolKey
                  : typeof rawTool.label === "string"
                    ? rawTool.label
                    : "",
            label:
              typeof rawTool.label === "string"
                ? rawTool.label
                : typeof rawTool.name === "string"
                  ? rawTool.name
                  : "业务数据查询",
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
  // 由持久化 messageStatus 推导整体状态；非 completed 时把仍 running 的步骤 finalize 为对应状态
  const agentExecutionStatus = deriveAgentExecutionStatus(messageStatus);
  const restoredSteps =
    agentExecutionStatus === "completed" ? steps : finalizeRunningSteps(steps, agentExecutionStatus);
  const summaryRaw = raw.summary as Record<string, unknown> | null | undefined;
  const summary: AgentExecutionSummary =
    summaryRaw && typeof summaryRaw === "object"
      ? {
          planCount: toNumber(summaryRaw.planCount, maxPlan),
          toolCallCount: toNumber(summaryRaw.toolCallCount, 0),
          evidenceCount: toNumber(summaryRaw.evidenceCount, 0),
          replanCount: toNumber(summaryRaw.replanCount, 0),
          durationMs: typeof summaryRaw.durationMs === "number" ? summaryRaw.durationMs : undefined,
          // 仅新数据持久化 terminalState；缺失时省略，页面按旧行为降级
          ...(isAgentTerminalState(summaryRaw.terminalState)
            ? { terminalState: summaryRaw.terminalState }
            : {})
        }
      : computeAgentExecutionSummary(steps) ?? {
          planCount: maxPlan,
          toolCallCount: 0,
          evidenceCount: 0,
          replanCount: 0
        };
  return {
    agentSteps: restoredSteps,
    agentExecutionStatus,
    agentExecutionSummary: summary,
    // planning 的 mode 无持久化来源，不恢复（省略）；terminalState 仅新数据存在
    ...(summary.terminalState ? { agentTerminalState: summary.terminalState } : {})
  };
}
