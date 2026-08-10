import type { AgentExecutionStep, AgentProgressPayload } from "@/types";

/**
 * Agent 进度「展示调度器」。
 *
 * 背景：SSE 多个 agent_progress 事件可能在一次 reader.read() 中一起到达，
 * 在同一 JS task 内 dispatch → React batching → 一次 paint 出很多行；
 * 且工具执行极快（几 ms），人眼无法感知 running 状态。
 *
 * 职责：
 * - Raw 事件实时接收不丢（seq/callId 保留），同一步骤（stepId 相同）原地更新，
 *   绝不产生 running/completed 两行
 * - running 立即可见（它是当前活动，保证至少有一次独立 paint）；
 *   终态（completed/warning/failed）按 minRunningVisibleMs 延迟揭示
 * - 单个定时器批量揭示到期项，revealAt 受 maxPresentationLagMs 上限约束，
 *   防止队列积压
 * - request-scoped：与消息一一对应，由 chatStore 在流收尾时 dispose
 */

export interface AgentProgressSchedulerOptions {
  /** running 最少展示时长；仅当 running 在时限内收到终态时生效（默认 150ms） */
  minRunningVisibleMs?: number;
  /** 展示延迟上限，防止队列积压（默认 400ms） */
  maxPresentationLagMs?: number;
  /** 可见步骤变化时回调（chatStore 用它 set 到消息） */
  onChange: (steps: AgentExecutionStep[]) => void;
}

/** 被 hold 的终态：未到 revealAt 不展示 */
interface PendingReveal {
  step: AgentExecutionStep;
  revealAt: number;
}

const DEFAULT_MIN_RUNNING_VISIBLE_MS = 150;
const DEFAULT_MAX_PRESENTATION_LAG_MS = 400;

/**
 * 构造稳定 stepId：
 * - 新后端带 callId：优先用 callId 构造 `plan-${plan}-${phase}-${callId}`，
 *   同一工具调用的 running→completed 共享 callId 可原地更新，
 *   同一 plan 内同工具的不同调用（不同 callId）各自成步，不再互相覆盖。
 * - 旧后端无 callId：保持原有按 (plan, phase, toolName) 合并的兼容行为，
 *   同 key 步骤已存在时复用其 stepId，否则按出现次数 +1 编号。
 */
export function buildAgentStepId(payload: AgentProgressPayload, steps: AgentExecutionStep[]): string {
  const plan = payload.plan ?? 1;
  const callId = payload.tool?.callId;
  if (callId) {
    // 同一工具调用的 running→completed 共享 callId，原地更新；不同调用（不同 callId）各自成步
    const existing = steps.find(
      (step) => step.tool?.callId === callId && step.plan === plan
    );
    if (existing) return existing.stepId;
    return `plan-${plan}-${payload.phase}-${callId}`;
  }
  // 旧后端无 callId：保持原有按 (plan, phase, toolName) 合并的行为
  const toolName = payload.tool?.name ?? "";
  const key = `${plan}|${payload.phase}|${toolName}`;
  const keyOf = (step: AgentExecutionStep) =>
    `${step.plan}|${step.phase}|${step.tool?.name ?? ""}`;
  const sameKey = steps.filter((step) => keyOf(step) === key);
  if (sameKey.length > 0) return sameKey[0].stepId;
  return `plan-${plan}-${payload.phase}-${toolName}-${sameKey.length + 1}`;
}

function buildStep(payload: AgentProgressPayload, stepId: string): AgentExecutionStep {
  return {
    stepId,
    seq: payload.seq,
    phase: payload.phase,
    status: payload.status,
    plan: payload.plan ?? 1,
    title: payload.title,
    detail: payload.detail,
    tool: payload.tool ?? undefined
  };
}

export class AgentProgressScheduler {
  private readonly minRunningVisibleMs: number;
  private readonly maxPresentationLagMs: number;
  private readonly onChange: (steps: AgentExecutionStep[]) => void;

  /** 可见逻辑步骤（按 seq 顺序追加）；每次变更生成新数组引用，供 React.memo 兜底 */
  private steps: AgentExecutionStep[] = [];
  /** stepId → 最近一次置为 running 的时刻 */
  private readonly runningAt = new Map<string, number>();
  /** stepId → 被 hold 的终态（未到 revealAt 不展示） */
  private readonly pending = new Map<string, PendingReveal>();
  /** 已处理过的 seq（每个 payload.seq 只处理一次） */
  private readonly seenSeqs = new Set<number>();
  /** 单个定时器：取最早 revealAt，到期批量揭示 */
  private timer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;

  constructor(options: AgentProgressSchedulerOptions) {
    this.minRunningVisibleMs = options.minRunningVisibleMs ?? DEFAULT_MIN_RUNNING_VISIBLE_MS;
    this.maxPresentationLagMs = options.maxPresentationLagMs ?? DEFAULT_MAX_PRESENTATION_LAG_MS;
    this.onChange = options.onChange;
  }

  push(payload: AgentProgressPayload): void {
    if (this.disposed) return;
    if (this.seenSeqs.has(payload.seq)) return;
    this.seenSeqs.add(payload.seq);
    if (import.meta.env.DEV) {
      console.debug("[agent raw]", {
        seq: payload.seq,
        phase: payload.phase,
        status: payload.status,
        receivedAt: Date.now()
      });
    }
    if (payload.phase === "complete") {
      // 收尾标记：不创建步骤；先收敛所有 pending 终态，再把仍 running 的步骤 finalize 为 completed
      this.finalizeCompleted();
      return;
    }
    if (payload.phase === "generation" && payload.status === "running") {
      // 答案生成开始：收敛所有被 hold 的终态（Timeline 动画不得增加 TTFT），再添加 generation 步骤
      this.flush();
    }
    const stepId = buildAgentStepId(payload, this.steps);
    const now = Date.now();
    if (payload.status === "running") {
      // running 必须立刻可见：原地更新/追加并 emit，同时记录 runningAt
      this.pending.delete(stepId);
      const updated = this.applyStep(buildStep(payload, stepId));
      this.runningAt.set(stepId, now);
      this.emit(updated);
      return;
    }
    // 终态（completed | warning | failed | cancelled | pending）
    const current = this.steps.find((step) => step.stepId === stepId);
    const runningStart = this.runningAt.get(stepId);
    const shouldHold =
      current?.status === "running" &&
      runningStart != null &&
      now - runningStart < this.minRunningVisibleMs;
    const terminal = buildStep(payload, stepId);
    if (shouldHold) {
      const revealAt = Math.min(
        Math.max(runningStart + this.minRunningVisibleMs, now),
        now + this.maxPresentationLagMs
      );
      this.pending.set(stepId, { step: terminal, revealAt });
      this.scheduleTimer();
    } else {
      this.pending.delete(stepId);
      this.runningAt.delete(stepId);
      this.applyStep(terminal);
      this.emit(terminal);
    }
  }

  /** 立即把所有 pending（被 hold 的终态）收敛到最终状态并 emit */
  flush(): void {
    if (this.disposed) return;
    if (this.pending.size === 0) return;
    let lastChanged: AgentExecutionStep | undefined;
    for (const { step } of this.pending.values()) {
      this.runningAt.delete(step.stepId);
      lastChanged = this.applyStep(step);
    }
    this.pending.clear();
    this.clearTimer();
    if (lastChanged) this.emit(lastChanged);
  }

  /** 丢弃 pending，所有 running 步骤 → cancelled，emit；之后 push 不再生效 */
  cancel(): void {
    if (this.disposed) return;
    this.pending.clear();
    this.clearTimer();
    let lastChanged: AgentExecutionStep | undefined;
    const next = this.steps.map((step) => {
      if (step.status !== "running") return step;
      const cancelled = { ...step, status: "cancelled" as const };
      lastChanged = cancelled;
      return cancelled;
    });
    if (lastChanged) {
      this.steps = next;
      this.emit(lastChanged);
    }
    this.disposed = true;
  }

  /** 丢弃 pending，仅最后一个 running 步骤 → failed，emit；之后 push 不再生效 */
  fail(): void {
    if (this.disposed) return;
    this.pending.clear();
    this.clearTimer();
    const lastRunningIndex = this.steps.reduce(
      (found, step, index) => (step.status === "running" ? index : found),
      -1
    );
    if (lastRunningIndex >= 0) {
      const failed = { ...this.steps[lastRunningIndex], status: "failed" as const };
      const next = [...this.steps];
      next[lastRunningIndex] = failed;
      this.steps = next;
      this.emit(failed);
    }
    this.disposed = true;
  }

  /** 清定时器，不再 emit（幂等） */
  dispose(): void {
    this.disposed = true;
    this.clearTimer();
    this.pending.clear();
    this.seenSeqs.clear();
  }

  /** 原地更新/追加步骤；返回更新后的步骤（供 DEV 日志定位最后一次变更） */
  private applyStep(next: AgentExecutionStep): AgentExecutionStep {
    const index = this.steps.findIndex((step) => step.stepId === next.stepId);
    if (index >= 0) {
      const updated = { ...this.steps[index], ...next };
      const steps = [...this.steps];
      steps[index] = updated;
      this.steps = steps;
      return updated;
    }
    this.steps = [...this.steps, next];
    return next;
  }

  private emit(lastChanged?: AgentExecutionStep): void {
    if (this.disposed) return;
    if (import.meta.env.DEV && lastChanged) {
      console.debug("[agent visible]", {
        seq: lastChanged.seq,
        phase: lastChanged.phase,
        status: lastChanged.status,
        renderedAt: Date.now()
      });
    }
    this.onChange(this.steps);
  }

  /** 单个定时器：取最早 revealAt，到期批量揭示 */
  private scheduleTimer(): void {
    if (this.timer != null) return;
    const revealAt = this.earliestRevealAt();
    if (revealAt == null) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.revealDue();
    }, Math.max(0, revealAt - Date.now()));
  }

  private earliestRevealAt(): number | null {
    let earliest: number | null = null;
    for (const { revealAt } of this.pending.values()) {
      if (earliest == null || revealAt < earliest) earliest = revealAt;
    }
    return earliest;
  }

  private revealDue(): void {
    const now = Date.now();
    let lastChanged: AgentExecutionStep | undefined;
    for (const [stepId, pendingItem] of this.pending) {
      if (pendingItem.revealAt > now) continue;
      this.pending.delete(stepId);
      this.runningAt.delete(stepId);
      lastChanged = this.applyStep(pendingItem.step);
    }
    if (lastChanged) this.emit(lastChanged);
    // 仍有未到期 pending：继续用单定时器排程
    if (this.pending.size > 0 && this.timer == null) {
      this.scheduleTimer();
    }
  }

  /** phase=complete 收尾：收敛 pending + 仍 running 的步骤 finalize 为 completed，一次 emit */
  private finalizeCompleted(): void {
    let lastChanged: AgentExecutionStep | undefined;
    if (this.pending.size > 0) {
      for (const { step } of this.pending.values()) {
        this.runningAt.delete(step.stepId);
        lastChanged = this.applyStep(step);
      }
      this.pending.clear();
      this.clearTimer();
    }
    if (this.steps.some((step) => step.status === "running")) {
      this.steps = this.steps.map((step) => {
        if (step.status !== "running") return step;
        const finalized = { ...step, status: "completed" as const };
        lastChanged = finalized;
        return finalized;
      });
    }
    if (lastChanged) this.emit(lastChanged);
  }

  private clearTimer(): void {
    if (this.timer != null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}

/** request-scoped 注册表：messageId → scheduler */
const schedulers = new Map<string, AgentProgressScheduler>();

/** 获取（不存在时创建）指定消息的调度器；已存在时忽略 createOptions */
export function getAgentProgressScheduler(
  messageId: string,
  createOptions: AgentProgressSchedulerOptions
): AgentProgressScheduler {
  let scheduler = schedulers.get(messageId);
  if (!scheduler) {
    scheduler = new AgentProgressScheduler(createOptions);
    schedulers.set(messageId, scheduler);
  }
  return scheduler;
}

/** dispose 并从注册表删除（幂等） */
export function disposeAgentProgressScheduler(messageId: string): void {
  const scheduler = schedulers.get(messageId);
  if (scheduler) {
    scheduler.dispose();
    schedulers.delete(messageId);
  }
}

export function hasAgentProgressScheduler(messageId: string): boolean {
  return schedulers.has(messageId);
}
