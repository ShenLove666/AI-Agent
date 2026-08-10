import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentExecutionStep, AgentProgressPayload } from "@/types";
import {
  AgentProgressScheduler,
  buildAgentStepId,
  disposeAgentProgressScheduler,
  getAgentProgressScheduler,
  hasAgentProgressScheduler
} from "./agentProgressPresentation";

/** 构造普通事件负载 */
function payload(
  seq: number,
  phase: AgentProgressPayload["phase"],
  status: AgentProgressPayload["status"],
  overrides: Partial<AgentProgressPayload> = {}
): AgentProgressPayload {
  return { seq, phase, status, title: `${phase}-${seq}`, ...overrides };
}

/** 构造 tool 事件负载（callId 可选，模拟新旧后端） */
function toolPayload(
  seq: number,
  status: "running" | "completed",
  callId: string | undefined,
  plan = 1
): AgentProgressPayload {
  return {
    seq,
    phase: "tool",
    status,
    plan,
    title: "业务数据查询",
    tool: {
      name: "commerce_search_association_rules",
      label: "购物篮关联规则",
      status,
      ...(callId ? { callId } : {})
    }
  };
}

describe("AgentProgressScheduler", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // DEV 调试日志不参与断言，静音避免刷屏（源代码行为不改）
    vi.spyOn(console, "debug").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("burst：同 tick 多事件合并为逻辑行（无 running+completed 双行），推进 ≥ minRunningVisibleMs 后终态 reveal", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    // 同一 tick 内一次性推入：planning running/completed、tool running/completed ×2、
    // review running/warning、replan completed
    scheduler.push(payload(1, "planning", "running", { title: "制定计划" }));
    scheduler.push(payload(2, "planning", "completed", { title: "制定计划" }));
    scheduler.push(toolPayload(3, "running", "call-1"));
    scheduler.push(toolPayload(4, "completed", "call-1"));
    scheduler.push(toolPayload(5, "running", "call-2"));
    scheduler.push(toolPayload(6, "completed", "call-2"));
    scheduler.push(payload(7, "review", "running", { title: "校验数据" }));
    scheduler.push(payload(8, "review", "warning", { title: "校验数据" }));
    scheduler.push(payload(9, "replan", "completed", { title: "重新规划" }));

    // 任意一次 emit 中同一 stepId 最多出现一次：绝不产生 running/completed 双行
    for (const steps of emitted) {
      const ids = steps.map((step) => step.stepId);
      expect(new Set(ids).size).toBe(ids.length);
    }

    // 合并后的逻辑行：planning、tool call-1、tool call-2、review、replan 各一行
    let latest = emitted[emitted.length - 1];
    expect(latest).toHaveLength(5);
    expect(latest.filter((step) => step.phase === "tool")).toHaveLength(2);
    expect(latest.filter((step) => step.phase === "tool" && step.tool?.callId === "call-1")).toHaveLength(1);
    // running 先行：终态被 hold，尚未 reveal
    expect(latest.find((step) => step.phase === "planning")?.status).toBe("running");
    expect(latest.find((step) => step.phase === "tool" && step.tool?.callId === "call-1")?.status).toBe("running");
    // replan 无先前 running（直接 completed）：立即 reveal
    expect(latest.find((step) => step.phase === "replan")?.status).toBe("completed");

    // 推进 ≥ minRunningVisibleMs：终态批量 reveal
    vi.advanceTimersByTime(200);
    latest = emitted[emitted.length - 1];
    expect(latest.map((step) => step.status)).toEqual([
      "completed",
      "completed",
      "completed",
      "warning",
      "completed"
    ]);
    // 行数不变：全部原地更新
    expect(latest).toHaveLength(5);
  });

  it("快速 tool：running 后同 tick completed → 先 emit running，推进 150ms 后同一行变 completed（行数不变）", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(toolPayload(2, "completed", "call-1"));

    // running 立即可见；completed 被 hold 不 emit
    expect(emitted).toHaveLength(1);
    let latest = emitted[emitted.length - 1];
    expect(latest).toHaveLength(1);
    expect(latest[0].status).toBe("running"); // 终态被 hold：running 先行

    vi.advanceTimersByTime(200);
    expect(emitted).toHaveLength(2);
    latest = emitted[emitted.length - 1];
    expect(latest).toHaveLength(1); // 同一步骤原地更新，绝不产生第二行
    expect(latest[0].status).toBe("completed");
    expect(latest[0].stepId).toBe("plan-1-tool-call-1");
  });

  it("flush：pending 未到期时立即收敛为终态", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(toolPayload(2, "completed", "call-1"));
    expect(emitted[emitted.length - 1][0].status).toBe("running");

    scheduler.flush();
    expect(emitted[emitted.length - 1]).toHaveLength(1);
    expect(emitted[emitted.length - 1][0].status).toBe("completed");

    // pending 已清空：推进时间不再有变化
    const countBefore = emitted.length;
    vi.advanceTimersByTime(300);
    expect(emitted.length).toBe(countBefore);
  });

  it("generation running 触发 flush：tool 终态在本次 push 内立即收敛", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(toolPayload(2, "completed", "call-1"));
    expect(emitted[emitted.length - 1][0].status).toBe("running");

    // 答案生成开始：push generation running
    scheduler.push(payload(3, "generation", "running", { title: "正在生成回答" }));

    const latest = emitted[emitted.length - 1];
    expect(latest.map((step) => step.phase)).toEqual(["tool", "generation"]);
    // tool 终态立即收敛（无需推进定时器），generation 正常添加
    expect(latest[0].status).toBe("completed");
    expect(latest[1].status).toBe("running");
  });

  it("cancel：丢弃 pending、running → cancelled、之后 push 不再生效", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(toolPayload(2, "completed", "call-1")); // 被 hold
    scheduler.push(toolPayload(3, "running", "call-2"));

    scheduler.cancel();

    const latest = emitted[emitted.length - 1];
    expect(latest.map((step) => step.status)).toEqual(["cancelled", "cancelled"]);
    // pending 无残留：推进时间不再有变化
    const countBefore = emitted.length;
    vi.advanceTimersByTime(300);
    expect(emitted.length).toBe(countBefore);

    // 之后 push 不再生效
    scheduler.push(toolPayload(4, "running", "call-3"));
    expect(emitted.length).toBe(countBefore);
    expect(emitted[emitted.length - 1]).toHaveLength(2);
  });

  it("fail：丢弃 pending、仅最后一个 running 步骤 → failed", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(payload(2, "planning", "completed", { title: "制定计划" }));
    scheduler.push(toolPayload(3, "running", "call-2"));
    scheduler.push(toolPayload(4, "completed", "call-2")); // 被 hold

    scheduler.fail();

    const latest = emitted[emitted.length - 1];
    expect(latest.map((step) => step.status)).toEqual(["running", "completed", "failed"]);
    // 仅最后一个 running 失败；已 completed 的不受影响
    expect(latest[2].tool?.callId).toBe("call-2");
  });

  it("seq 去重：每个 payload.seq 只处理一次", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    const countBefore = emitted.length;
    // 重复 seq：忽略
    scheduler.push(toolPayload(1, "completed", "call-1"));
    scheduler.push(toolPayload(1, "running", "call-2"));
    expect(emitted.length).toBe(countBefore);
    expect(emitted[emitted.length - 1]).toHaveLength(1);
  });

  it("隔离：不同 messageId 的 scheduler 互不影响，dispose 后不再 emit", () => {
    const a: AgentExecutionStep[][] = [];
    const b: AgentExecutionStep[][] = [];
    const sa = getAgentProgressScheduler("msg-a", { onChange: (steps) => a.push(steps) });
    const sb = getAgentProgressScheduler("msg-b", { onChange: (steps) => b.push(steps) });
    expect(hasAgentProgressScheduler("msg-a")).toBe(true);
    expect(hasAgentProgressScheduler("msg-b")).toBe(true);
    expect(sa).not.toBe(sb);

    sa.push(toolPayload(1, "running", "call-1"));
    expect(a).toHaveLength(1);
    expect(b).toHaveLength(0);

    disposeAgentProgressScheduler("msg-a");
    expect(hasAgentProgressScheduler("msg-a")).toBe(false);
    // disposed 后 push 不再 emit（原有实例引用仍可用，但已失效）
    sa.push(toolPayload(2, "completed", "call-1"));
    expect(a).toHaveLength(1);

    // 同 id 重建：全新实例，互不污染
    const sa2 = getAgentProgressScheduler("msg-a", { onChange: (steps) => a.push(steps) });
    expect(sa2).not.toBe(sa);
    sa2.push(toolPayload(1, "running", "call-9"));
    expect(a).toHaveLength(2);
    expect(a[1][0].tool?.callId).toBe("call-9");

    disposeAgentProgressScheduler("msg-a");
    disposeAgentProgressScheduler("msg-b");
  });

  it("getAgentProgressScheduler：已存在时复用并忽略 createOptions", () => {
    const calls: AgentExecutionStep[][] = [];
    const first = getAgentProgressScheduler("reuse-1", { onChange: (steps) => calls.push(steps) });
    const second = getAgentProgressScheduler("reuse-1", {
      onChange: () => calls.push([])
    });
    expect(second).toBe(first);

    first.push(toolPayload(1, "running", "call-1"));
    expect(calls).toHaveLength(1); // 只走首次注册的 onChange
    expect(calls[0][0].status).toBe("running");
    disposeAgentProgressScheduler("reuse-1");
  });

  it("maxPresentationLagMs：hold 上限不超过 now + lag", () => {
    const emitted: AgentExecutionStep[][] = [];
    const scheduler = new AgentProgressScheduler({
      minRunningVisibleMs: 1000,
      maxPresentationLagMs: 200,
      onChange: (steps) => emitted.push(steps)
    });

    scheduler.push(toolPayload(1, "running", "call-1"));
    scheduler.push(toolPayload(2, "completed", "call-1"));
    expect(emitted[emitted.length - 1][0].status).toBe("running");

    // running 需 1000ms，但保底 200ms 后必须 reveal
    vi.advanceTimersByTime(300);
    expect(emitted[emitted.length - 1][0].status).toBe("completed");
  });
});

describe("buildAgentStepId", () => {
  it("callId 优先；无 callId 走 (plan, phase, toolName) 合并兼容", () => {
    // 带 callId：构造 plan-phase-callId
    expect(buildAgentStepId(toolPayload(1, "running", "call-1"), [])).toBe("plan-1-tool-call-1");
    // 同 callId 原地复用（running→completed 共享一行）
    const steps: AgentExecutionStep[] = [
      {
        stepId: "plan-1-tool-call-1",
        seq: 1,
        phase: "tool",
        status: "running",
        plan: 1,
        title: "业务数据查询",
        tool: { name: "commerce_search_association_rules", label: "购物篮关联规则", status: "running", callId: "call-1" }
      }
    ];
    expect(buildAgentStepId(toolPayload(2, "completed", "call-1"), steps)).toBe("plan-1-tool-call-1");

    // 无 callId：同 key 复用，新 key 按出现次数编号
    const noCallIdSteps: AgentExecutionStep[] = [
      {
        stepId: "plan-1-tool-commerce_search_association_rules-1",
        seq: 1,
        phase: "tool",
        status: "completed",
        plan: 1,
        title: "业务数据查询",
        tool: { name: "commerce_search_association_rules", label: "购物篮关联规则", status: "completed" }
      }
    ];
    expect(buildAgentStepId(toolPayload(2, "running", undefined), noCallIdSteps)).toBe(
      "plan-1-tool-commerce_search_association_rules-1"
    );
    // 非 tool 阶段（无 toolName）：plan-phase--n 编号
    expect(buildAgentStepId(payload(1, "planning", "completed"), [])).toBe("plan-1-planning--1");
  });
});
