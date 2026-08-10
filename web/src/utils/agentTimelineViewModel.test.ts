import { describe, expect, it } from "vitest";
import type { AgentExecutionStep } from "@/types";
import { buildAgentTimelineViewModel } from "./agentTimelineViewModel";

/** 构造时间线步骤 */
function makeStep(
  stepId: string,
  seq: number,
  phase: AgentExecutionStep["phase"],
  status: AgentExecutionStep["status"],
  plan: number,
  title: string,
  extra: Partial<AgentExecutionStep> = {}
): AgentExecutionStep {
  return { stepId, seq, phase, status, plan, title, ...extra };
}

const ASSOCIATION_TOOL = {
  name: "commerce_search_association_rules",
  label: "购物篮关联规则",
  status: "completed" as const,
  callId: "call-1",
  evidenceCount: 3,
  durationMs: 120
};

describe("buildAgentTimelineViewModel", () => {
  it("单轮：planning running+completed 合并为一行（同一 stepId）", () => {
    const vm = buildAgentTimelineViewModel(
      [makeStep("plan-1-planning-1", 1, "planning", "completed", 1, "制定计划")],
      { status: "completed" }
    );
    expect(vm.rows).toHaveLength(1);
    expect(vm.rows[0]).toMatchObject({
      key: "plan-1-planning-1",
      kind: "step",
      phase: "planning",
      status: "completed",
      title: "制定计划",
      plan: 1,
      roundIndex: 0
    });
    expect(vm.currentActivityTitle).toBeNull();
    expect(vm.summaryText).toBe("已完成分析");
    expect(vm.hasRunning).toBe(false);
    expect(vm.collapsedRoundCount).toBe(0);
    expect(vm.toolCallCount).toBe(0);
    expect(vm.evidenceCount).toBe(0);
  });

  it("多轮：旧轮压缩为 round-summary，当前轮完整展示，generation 在最后", () => {
    const steps = [
      makeStep("plan-1-planning-1", 1, "planning", "completed", 1, "制定计划"),
      makeStep("plan-1-tool-call-1", 2, "tool", "completed", 1, "业务数据查询", {
        tool: { ...ASSOCIATION_TOOL }
      }),
      makeStep("plan-2-tool-call-2", 3, "tool", "completed", 2, "业务数据查询", {
        tool: {
          name: "commerce_product_profile",
          label: "商品画像查询",
          status: "completed",
          callId: "call-2",
          evidenceCount: 2
        }
      }),
      makeStep("plan-2-generation-1", 4, "generation", "completed", 2, "生成回答")
    ];
    const vm = buildAgentTimelineViewModel(steps, {
      status: "completed",
      summary: { planCount: 2, toolCallCount: 2, evidenceCount: 5, replanCount: 0 }
    });

    expect(vm.rows.map((row) => row.kind)).toEqual(["round-summary", "step", "step"]);
    // 旧轮摘要行
    expect(vm.rows[0]).toMatchObject({
      key: "round-1",
      kind: "round-summary",
      status: "completed",
      title: "第一轮查询完成 · 1 项数据源 · 找到 3 条数据",
      plan: 1,
      roundIndex: 0
    });
    // 当前轮 tool 行：title 用 label，携带 tool 信息，detail 缺省为「找到 n 条相关数据」
    expect(vm.rows[1]).toMatchObject({
      key: "plan-2-tool-call-2",
      kind: "step",
      phase: "tool",
      status: "completed",
      title: "商品画像查询",
      detail: "找到 2 条相关数据",
      tool: { label: "商品画像查询", durationMs: null, evidenceCount: 2 },
      plan: 2,
      roundIndex: 1
    });
    // generation 排在最后，roundIndex = -1
    expect(vm.rows[2]).toMatchObject({
      key: "plan-2-generation-1",
      kind: "step",
      phase: "generation",
      title: "生成回答",
      roundIndex: -1
    });
    expect(vm.collapsedRoundCount).toBe(1);
    expect(vm.summaryText).toBe("已完成分析 · 2 次查询 · 核验 5 条证据");
    expect(vm.toolCallCount).toBe(2);
    expect(vm.evidenceCount).toBe(5);
    expect(vm.hasRunning).toBe(false);
  });

  it("expandedRounds：展开旧轮时输出该轮全部 step 行（不再压缩）", () => {
    const steps = [
      makeStep("plan-1-planning-1", 1, "planning", "completed", 1, "制定计划"),
      makeStep("plan-1-tool-call-1", 2, "tool", "completed", 1, "业务数据查询", {
        tool: { ...ASSOCIATION_TOOL }
      }),
      makeStep("plan-2-tool-call-2", 3, "tool", "completed", 2, "业务数据查询", {
        tool: { name: "n", label: "商品画像查询", status: "completed", callId: "call-2" }
      })
    ];
    const vm = buildAgentTimelineViewModel(steps, {
      status: "completed",
      expandedRounds: new Set([0])
    });
    expect(vm.rows.map((row) => row.kind)).toEqual(["step", "step", "step"]);
    expect(vm.rows.map((row) => row.roundIndex)).toEqual([0, 0, 1]);
    // 旧轮 tool 行展开后完整展示
    expect(vm.rows[0]).toMatchObject({ kind: "step", phase: "planning", title: "制定计划" });
    expect(vm.rows[1]).toMatchObject({ phase: "tool", title: "购物篮关联规则" });
    expect(vm.collapsedRoundCount).toBe(0);
  });

  it("replan 合并：连续的 review warning + 紧随 replan → 一行 replan", () => {
    const vm = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-review-1", 1, "review", "warning", 1, "数据不足"),
        makeStep("plan-1-review-2", 2, "review", "warning", 1, "再次校验"),
        makeStep("plan-1-replan-1", 3, "replan", "completed", 1, "调整查询策略")
      ],
      { status: "completed", summary: { planCount: 1, toolCallCount: 0, evidenceCount: 0, replanCount: 1 } }
    );
    expect(vm.rows).toHaveLength(1);
    expect(vm.rows[0]).toMatchObject({
      key: "plan-1-replan-1",
      kind: "replan",
      phase: "replan",
      status: "completed",
      title: "数据不足，已调整查询策略",
      detail: "正在补充查询其他数据来源",
      plan: 1,
      roundIndex: 0
    });
    // 原始 review/replan 两行不得同时出现
    expect(vm.rows.some((row) => row.phase === "review")).toBe(false);
  });

  it("escalate：review warning 无紧随 replan 保持独立行", () => {
    const vm = buildAgentTimelineViewModel(
      [makeStep("plan-1-review-1", 1, "review", "warning", 1, "数据不足，已转人工")],
      { status: "completed" }
    );
    expect(vm.rows).toHaveLength(1);
    expect(vm.rows[0]).toMatchObject({
      kind: "step",
      phase: "review",
      status: "warning",
      title: "数据不足，已转人工"
    });
  });

  it("review warning 后隔了其他行：不合并", () => {
    const vm = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-review-1", 1, "review", "warning", 1, "数据不足"),
        makeStep("plan-1-tool-1", 2, "tool", "completed", 1, "业务数据查询", {
          tool: { name: "n", label: "商品画像查询", status: "completed", evidenceCount: 1 }
        }),
        makeStep("plan-1-replan-1", 3, "replan", "completed", 1, "调整查询策略")
      ],
      { status: "completed" }
    );
    expect(vm.rows.map((row) => row.kind)).toEqual(["step", "step", "step"]);
    expect(vm.rows[0]).toMatchObject({ phase: "review", status: "warning", title: "数据不足" });
    expect(vm.rows[2]).toMatchObject({ kind: "step", phase: "replan" });
  });

  it("evidence 文案：0 条统一覆盖（含「关联」变体），禁止显示 0 条证据", () => {
    const withAssociation = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-tool-1", 1, "tool", "completed", 1, "业务数据查询", {
          tool: { name: "n", label: "购物篮关联规则", status: "completed", evidenceCount: 0 }
        })
      ],
      { status: "completed" }
    );
    expect(withAssociation.rows[0].title).toBe("购物篮关联规则");
    expect(withAssociation.rows[0].detail).toBe("暂未找到有效关联数据");

    const plain = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-tool-2", 1, "tool", "completed", 1, "业务数据查询", {
          tool: { name: "n", label: "商品销量查询", status: "completed", evidenceCount: 0 }
        })
      ],
      { status: "completed" }
    );
    expect(plain.rows[0].detail).toBe("暂未找到有效数据");
  });

  it("evidence 文案：正数优先用 step.detail，缺省为「找到 n 条相关数据」", () => {
    const withDetail = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-tool-1", 1, "tool", "completed", 1, "业务数据查询", {
          detail: "命中品牌 A 的 2 条记录",
          tool: { name: "n", label: "商品画像查询", status: "completed", evidenceCount: 2 }
        })
      ],
      { status: "completed" }
    );
    expect(withDetail.rows[0].detail).toBe("命中品牌 A 的 2 条记录");

    const defaultDetail = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-tool-2", 1, "tool", "completed", 1, "业务数据查询", {
          tool: { name: "n", label: "商品画像查询", status: "completed", evidenceCount: 2 }
        })
      ],
      { status: "completed" }
    );
    expect(defaultDetail.rows[0].detail).toBe("找到 2 条相关数据");
  });

  it("currentActivityTitle：tool running → 正在查询{label}…；generation running → 正在生成回答…；无 running → null", () => {
    const toolVm = buildAgentTimelineViewModel(
      [
        makeStep("plan-1-tool-1", 1, "tool", "running", 1, "业务数据查询", {
          tool: { name: "n", label: "商品关联分析", status: "running" }
        })
      ],
      { status: "running" }
    );
    expect(toolVm.currentActivityTitle).toBe("正在查询商品关联分析…");

    const generationVm = buildAgentTimelineViewModel(
      [makeStep("plan-1-generation-1", 1, "generation", "running", 1, "正在生成回答")],
      { status: "running" }
    );
    expect(generationVm.currentActivityTitle).toBe("正在生成回答…");

    const doneVm = buildAgentTimelineViewModel(
      [makeStep("plan-1-planning-1", 1, "planning", "completed", 1, "制定计划")],
      { status: "completed" }
    );
    expect(doneVm.currentActivityTitle).toBeNull();
  });

  it("currentActivityTitle：其他行去掉句尾标点再加省略号", () => {
    const vm = buildAgentTimelineViewModel(
      [makeStep("plan-1-planning-1", 1, "planning", "running", 1, "正在制定查询计划。")],
      { status: "running" }
    );
    expect(vm.currentActivityTitle).toBe("正在制定查询计划…");
  });

  it("summaryText：running/failed/cancelled/completed（含计数），无 summary 时按 rows 现算", () => {
    const toolSteps = [
      makeStep("plan-1-tool-1", 1, "tool", "completed", 1, "业务数据查询", {
        tool: { name: "n", label: "购物篮关联规则", status: "completed", evidenceCount: 3 }
      })
    ];
    expect(buildAgentTimelineViewModel(toolSteps, { status: "running" }).summaryText).toBe(
      "正在分析并查询相关数据…"
    );
    expect(buildAgentTimelineViewModel(toolSteps, { status: "failed" }).summaryText).toBe("处理失败");
    expect(buildAgentTimelineViewModel(toolSteps, { status: "cancelled" }).summaryText).toBe("已停止处理");
    // 无 summary：按 rows 现算（tool 行 completed 计数、evidence 求和）
    expect(buildAgentTimelineViewModel(toolSteps, { status: "completed" }).summaryText).toBe(
      "已完成分析 · 1 次查询 · 核验 3 条证据"
    );
    // 无工具步骤：只有基础文案
    expect(
      buildAgentTimelineViewModel(
        [makeStep("plan-1-planning-1", 1, "planning", "completed", 1, "制定计划")],
        { status: "completed" }
      ).summaryText
    ).toBe("已完成分析");
  });

  it("无 steps / 空数组：空 rows + 按 status 的 summaryText", () => {
    const empty = buildAgentTimelineViewModel(undefined, { status: "completed" });
    expect(empty.rows).toEqual([]);
    expect(empty.summaryText).toBe("已完成分析");
    expect(empty.currentActivityTitle).toBeNull();
    expect(empty.hasRunning).toBe(false);
    expect(buildAgentTimelineViewModel([], { status: "failed" }).summaryText).toBe("处理失败");
    expect(buildAgentTimelineViewModel([], { status: "cancelled" }).summaryText).toBe("已停止处理");
    expect(buildAgentTimelineViewModel([], { status: "running" }).summaryText).toBe(
      "正在分析并查询相关数据…"
    );
  });

  it("hasRunning：任一 running（含 pending）步骤", () => {
    expect(
      buildAgentTimelineViewModel(
        [
          makeStep("plan-1-tool-1", 1, "tool", "running", 1, "业务数据查询", {
            tool: { name: "n", label: "商品画像查询", status: "running" }
          })
        ],
        { status: "running" }
      ).hasRunning
    ).toBe(true);
    expect(
      buildAgentTimelineViewModel(
        [
          makeStep("plan-1-tool-1", 1, "tool", "completed", 1, "业务数据查询", {
            tool: { name: "n", label: "商品画像查询", status: "completed" }
          })
        ],
        { status: "completed" }
      ).hasRunning
    ).toBe(false);
  });

  it("轮号中文数字：1-3 中文，其余阿拉伯数字；evidence 为 0 时摘要显示暂无有效结果", () => {
    const steps: AgentExecutionStep[] = [];
    let seq = 1;
    for (let plan = 1; plan <= 5; plan += 1) {
      steps.push(
        makeStep(`plan-${plan}-tool-${plan}`, seq, "tool", "completed", plan, "业务数据查询", {
          tool: { name: "n", label: `工具${plan}`, status: "completed", evidenceCount: 0 }
        })
      );
      seq += 1;
    }
    const vm = buildAgentTimelineViewModel(steps, { status: "completed" });
    expect(vm.collapsedRoundCount).toBe(4);
    expect(vm.rows[0].title).toBe("第一轮查询完成 · 1 项数据源 · 暂无有效结果");
    expect(vm.rows[1].title).toBe("第二轮查询完成 · 1 项数据源 · 暂无有效结果");
    expect(vm.rows[2].title).toBe("第三轮查询完成 · 1 项数据源 · 暂无有效结果");
    expect(vm.rows[3].title).toBe("第4轮查询完成 · 1 项数据源 · 暂无有效结果");
    // 当前轮（第 5 轮）完整展示
    expect(vm.rows[4]).toMatchObject({ kind: "step", phase: "tool", roundIndex: 4 });
  });
});
