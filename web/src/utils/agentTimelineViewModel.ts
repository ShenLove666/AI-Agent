import type {
  AgentExecutionStatus,
  AgentExecutionStep,
  AgentExecutionSummary,
  AgentProgressStatus
} from "@/types";

/**
 * Agent 时间线「展示视图模型」（纯函数，无副作用）：
 * 把调度器产出的逻辑步骤（agentSteps）转换为用户可读的拍平行：
 * - 按 plan 分组，最后一轮为当前轮完整展示，更早的轮压缩为 round-summary 行
 *   （除非在 expandedRounds 中——展开时输出该轮全部 step 行）
 * - (review, warning) + 紧随其后的 (replan, *) 合并为一行 replan 提示
 * - generation 是全局阶段，统一排在所有轮之后（roundIndex = -1）
 */

export type TimelineRowKind = "step" | "round-summary" | "replan";

export interface TimelineRow {
  /** stepId 或 round-summary 的稳定 key */
  key: string;
  kind: TimelineRowKind;
  /** 内部阶段（图标用），generation 行 phase="generation" */
  phase: string;
  status: "running" | "completed" | "warning" | "failed" | "cancelled";
  title: string;
  detail?: string;
  /** 仅 tool 行携带，供 UI 右侧显示耗时/证据数 */
  tool?: { label: string; durationMs?: number | null; evidenceCount?: number | null } | null;
  /** 内部保留（状态管理/Trace 用），UI 不展示 */
  plan: number;
  /** 0 起；generation 行 = -1 */
  roundIndex: number;
}

export interface AgentTimelineViewModel {
  /** 用户可见行（拍平），顺序即渲染顺序 */
  rows: TimelineRow[];
  /** 运行中头部动态标题（最后 running 行），无 running 时 null */
  currentActivityTitle: string | null;
  summaryText: string;
  /** 被压缩为摘要的旧轮数 */
  collapsedRoundCount: number;
  toolCallCount: number;
  evidenceCount: number;
  replanCount: number;
  hasRunning: boolean;
}

const CN_NUMERALS: Record<number, string> = { 1: "一", 2: "二", 3: "三" };

function cnNumber(n: number): string {
  return CN_NUMERALS[n] ?? String(n);
}

/** pending 视觉上等同 running（即将执行） */
function normalizeStatus(status: AgentProgressStatus): TimelineRow["status"] {
  return status === "pending" ? "running" : status;
}

/** 单条 step → 用户可见行（tool 行标题/详情/工具信息有专门规则） */
function stepToRow(step: AgentExecutionStep, roundIndex: number): TimelineRow {
  const status = normalizeStatus(step.status);
  if (step.phase === "tool" && step.tool) {
    const evidenceCount = step.tool.evidenceCount ?? null;
    let detail: string | undefined;
    if (evidenceCount != null && evidenceCount > 0) {
      // 优先用后端详情，缺省为「找到 n 条相关数据」
      detail =
        step.detail && step.detail.trim() ? step.detail : `找到 ${evidenceCount} 条相关数据`;
    } else if (evidenceCount === 0) {
      // 禁止显示 "0 条证据" 作为主文案
      detail = step.tool.label.includes("关联")
        ? "暂未找到有效关联数据"
        : "暂未找到有效数据";
    } else {
      detail = step.detail;
    }
    return {
      key: step.stepId,
      kind: "step",
      phase: step.phase,
      status,
      title: step.tool.label ?? step.title,
      detail,
      tool: {
        label: step.tool.label,
        durationMs: step.tool.durationMs ?? null,
        evidenceCount
      },
      plan: step.plan,
      roundIndex
    };
  }
  return {
    key: step.stepId,
    kind: "step",
    phase: step.phase,
    status,
    title: step.title,
    detail: step.detail,
    plan: step.plan,
    roundIndex
  };
}

/**
 * 某轮内的行构建：
 * - 连续的 (review, warning) 行 + 紧随其后的 (replan, *) 行 → 合并为一行 replan；
 *   review warning 若无紧随 replan（如 escalate 场景）保持独立行
 * - 原始 review/replan 两行不得同时出现在 rows 中
 */
function buildRoundRows(roundSteps: AgentExecutionStep[], roundIndex: number): TimelineRow[] {
  const rows: TimelineRow[] = [];
  let i = 0;
  while (i < roundSteps.length) {
    const step = roundSteps[i];
    if (step.phase === "review" && step.status === "warning") {
      let j = i;
      while (
        j < roundSteps.length &&
        roundSteps[j].phase === "review" &&
        roundSteps[j].status === "warning"
      ) {
        j += 1;
      }
      const next = roundSteps[j];
      if (next && next.phase === "replan") {
        rows.push({
          key: next.stepId,
          kind: "replan",
          phase: "replan",
          status: "completed",
          title: "数据不足，已调整查询策略",
          detail: "正在补充查询其他数据来源",
          plan: next.plan,
          roundIndex
        });
        i = j + 1;
        continue;
      }
      // 无紧随 replan：保持独立行（下方原样输出本行）
    }
    rows.push(stepToRow(step, roundIndex));
    i += 1;
  }
  return rows;
}

/** 旧轮压缩为一条 round-summary 行 */
function buildRoundSummaryRow(
  plan: number,
  roundIndex: number,
  roundSteps: AgentExecutionStep[]
): TimelineRow {
  const toolSteps = roundSteps.filter((step) => step.phase === "tool");
  const toolCount = toolSteps.length;
  const evidenceCount = toolSteps.reduce((sum, step) => sum + (step.tool?.evidenceCount ?? 0), 0);
  let title = `第${cnNumber(roundIndex + 1)}轮查询完成 · ${toolCount} 项数据源`;
  title += evidenceCount > 0 ? ` · 找到 ${evidenceCount} 条数据` : ` · 暂无有效结果`;
  return {
    key: `round-${plan}`,
    kind: "round-summary",
    phase: "tool",
    status: "completed",
    title,
    plan,
    roundIndex
  };
}

/** 无 summary 时的现算口径（与 computeAgentExecutionSummary 语义一致） */
function computeCountsFromSteps(steps: AgentExecutionStep[]) {
  const toolSteps = steps.filter((step) => step.phase === "tool" && step.tool);
  const toolCallCount = toolSteps.filter(
    (step) => step.status === "completed" || step.status === "failed"
  ).length;
  const evidenceCount = toolSteps.reduce(
    (sum, step) => sum + (step.tool?.status === "completed" ? step.tool.evidenceCount ?? 0 : 0),
    0
  );
  const replanCount = steps.filter((step) => step.phase === "replan").length;
  return { toolCallCount, evidenceCount, replanCount };
}

export function buildAgentTimelineViewModel(
  steps: AgentExecutionStep[] | undefined,
  options: {
    status: AgentExecutionStatus;
    summary?: AgentExecutionSummary | null;
    /** 用户点「查看详情」展开的旧轮（roundIndex 集合） */
    expandedRounds?: ReadonlySet<number>;
  }
): AgentTimelineViewModel {
  const all = steps ?? [];
  // generation 是全局阶段：不挂任何轮，统一排在所有轮之后
  const generationSteps = all.filter((step) => step.phase === "generation");
  const planSteps = all.filter((step) => step.phase !== "generation");

  // 按 plan 分组（保持 seq 序；轮序 = plan 升序）
  const planOrder: number[] = [];
  const byPlan = new Map<number, AgentExecutionStep[]>();
  for (const step of planSteps) {
    const list = byPlan.get(step.plan);
    if (list) {
      list.push(step);
    } else {
      byPlan.set(step.plan, [step]);
      planOrder.push(step.plan);
    }
  }
  planOrder.sort((a, b) => a - b);

  const expandedRounds = options.expandedRounds;
  const rows: TimelineRow[] = [];
  let collapsedRoundCount = 0;
  planOrder.forEach((plan, roundIndex) => {
    const roundSteps = byPlan.get(plan) ?? [];
    const isCurrentRound = roundIndex === planOrder.length - 1;
    if (!isCurrentRound && !(expandedRounds && expandedRounds.has(roundIndex))) {
      collapsedRoundCount += 1;
      rows.push(buildRoundSummaryRow(plan, roundIndex, roundSteps));
      return;
    }
    rows.push(...buildRoundRows(roundSteps, roundIndex));
  });
  for (const step of generationSteps) {
    rows.push(stepToRow(step, -1));
  }

  // currentActivityTitle：最后一条 running 行；tool 行 → 正在查询{label}…；其他 → 去句尾标点 + …
  let currentActivityTitle: string | null = null;
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (row.status !== "running") continue;
    if (row.phase === "tool" && row.tool) {
      currentActivityTitle = `正在查询${row.tool.label}…`;
    } else {
      currentActivityTitle = `${row.title.replace(/[。.…\s]+$/, "")}…`;
    }
    break;
  }

  const computed = computeCountsFromSteps(all);
  const toolCallCount = options.summary?.toolCallCount ?? computed.toolCallCount;
  const evidenceCount = options.summary?.evidenceCount ?? computed.evidenceCount;
  const replanCount = options.summary?.replanCount ?? computed.replanCount;

  const summaryText = (() => {
    if (options.status === "running") return "正在分析并查询相关数据…";
    if (options.status === "failed") return "处理失败";
    if (options.status === "cancelled") return "已停止处理";
    // completed：无 summary 时按 rows 现算（tool 行 completed/failed 计数、evidence 求和）
    const rowToolCalls = rows.filter(
      (row) =>
        row.kind === "step" && row.phase === "tool" &&
        (row.status === "completed" || row.status === "failed")
    ).length;
    const rowEvidence = rows.reduce((sum, row) => {
      if (row.kind === "step" && row.phase === "tool" && row.tool?.evidenceCount != null) {
        return sum + row.tool.evidenceCount;
      }
      return sum;
    }, 0);
    const calls = options.summary?.toolCallCount ?? rowToolCalls;
    const evidence = options.summary?.evidenceCount ?? rowEvidence;
    let text = "已完成分析";
    if (calls > 0) text += ` · ${calls} 次查询`;
    if (evidence > 0) text += ` · 核验 ${evidence} 条证据`;
    return text;
  })();

  return {
    rows,
    currentActivityTitle,
    summaryText,
    collapsedRoundCount,
    toolCallCount,
    evidenceCount,
    replanCount,
    hasRunning: all.some((step) => step.status === "running" || step.status === "pending")
  };
}
