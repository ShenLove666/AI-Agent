import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { AgentExecutionTimeline } from "./AgentExecutionTimeline";
import type { AgentExecutionStep, AgentExecutionSummary } from "@/types";

function makeStep(overrides: Partial<AgentExecutionStep> = {}): AgentExecutionStep {
  return {
    stepId: "plan-1-tool--1",
    seq: 1,
    phase: "tool",
    status: "completed",
    plan: 1,
    title: "查询商品关联数据",
    ...overrides
  };
}

function makeManySteps(count: number): AgentExecutionStep[] {
  return Array.from({ length: count }, (_, i) =>
    makeStep({ stepId: `step-${i + 1}`, seq: i + 1, title: `步骤 ${i + 1}` })
  );
}

const completedSummary: AgentExecutionSummary = {
  planCount: 1,
  toolCallCount: 1,
  evidenceCount: 6,
  replanCount: 0
};

const toolStep = makeStep({
  title: "查询商品关联数据",
  tool: {
    name: "commerce.search_association_rules",
    label: "商品关联分析",
    status: "completed",
    argumentsSummary: "牛肉 · 最多 10 条",
    durationMs: 14,
    evidenceCount: 6
  }
});

describe("AgentExecutionTimeline", () => {
  afterEach(() => {
    cleanup();
  });

  it("running 态显示动态状态行（最后一个 running 步骤标题 + 副标题）", () => {
    render(
      <AgentExecutionTimeline
        status="running"
        steps={[
          makeStep({
            stepId: "plan-1-planning--1",
            seq: 1,
            phase: "planning",
            status: "running",
            title: "正在制定查询计划",
            detail: "准备查询商品关联数据"
          })
        ]}
      />
    );

    expect(screen.getByText("正在制定查询计划…")).toBeInTheDocument();
    expect(screen.getByText("Agent 正在调用业务工具并核验证据")).toBeInTheDocument();
    expect(screen.getByText("Agent 执行过程")).toBeInTheDocument();
  });

  it("running 态无进行中步骤时显示「正在分析问题…」", () => {
    render(
      <AgentExecutionTimeline
        status="running"
        steps={[makeStep({ stepId: "plan-1-review--1", seq: 1, phase: "review" })]}
      />
    );

    expect(screen.getByText("正在分析问题…")).toBeInTheDocument();
  });

  it("running 态只展示最近 5 步，更早步骤折叠为「已省略更早 N 步」", () => {
    render(
      <AgentExecutionTimeline status="running" steps={makeManySteps(8)} summary={null} />
    );

    // 最近 5 步（seq 4~8）可见
    for (const seq of [4, 5, 6, 7, 8]) {
      expect(screen.getByText(`步骤 ${seq}`)).toBeInTheDocument();
    }
    // 更早步骤（seq 1~3）被折叠
    for (const seq of [1, 2, 3]) {
      expect(screen.queryByText(`步骤 ${seq}`)).not.toBeInTheDocument();
    }
    expect(
      screen.getByRole("button", { name: "已省略更早 3 步" })
    ).toBeInTheDocument();
  });

  it("running 态点击「已省略更早 N 步」后展示全部步骤", () => {
    render(
      <AgentExecutionTimeline status="running" steps={makeManySteps(8)} summary={null} />
    );

    fireEvent.click(screen.getByRole("button", { name: "已省略更早 3 步" }));

    for (let seq = 1; seq <= 8; seq += 1) {
      expect(screen.getByText(`步骤 ${seq}`)).toBeInTheDocument();
    }
    expect(
      screen.queryByRole("button", { name: "已省略更早 3 步" })
    ).not.toBeInTheDocument();
  });

  it("非 running（用户主动展开）时展示全部步骤，不出现省略行", () => {
    render(
      <AgentExecutionTimeline status="completed" steps={makeManySteps(8)} summary={null} />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    for (let seq = 1; seq <= 8; seq += 1) {
      expect(screen.getByText(`步骤 ${seq}`)).toBeInTheDocument();
    }
    expect(screen.queryByText(/已省略更早/)).not.toBeInTheDocument();
  });

  it("completed 后默认折叠为一行摘要（含查询次数与证据数），不展示步骤", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        steps={[toolStep]}
        summary={completedSummary}
      />
    );

    expect(
      screen.getByText("已完成 Agent 分析 · 1 次查询 · 6 条证据")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看执行过程/ })).toBeInTheDocument();
    expect(screen.queryByText("查询商品关联数据")).not.toBeInTheDocument();
  });

  it("展开后展示步骤（含 tool label、durationMs、evidenceCount），单计划不显示分组标题", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        steps={[toolStep]}
        summary={completedSummary}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    expect(screen.getByText("查询商品关联数据")).toBeInTheDocument();
    expect(screen.getByText("商品关联分析")).toBeInTheDocument();
    expect(screen.getByText("牛肉 · 最多 10 条")).toBeInTheDocument();
    expect(screen.getByText("14ms")).toBeInTheDocument();
    expect(screen.getByText("6 条证据")).toBeInTheDocument();
    expect(screen.queryByText("计划 1")).not.toBeInTheDocument();
  });

  it("多计划时按 plan 分组展示「计划 N」标题", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({ stepId: "a", seq: 1, plan: 1, title: "第一轮查询" }),
          makeStep({ stepId: "b", seq: 2, plan: 2, title: "第二轮重查" })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    expect(screen.getByText("计划 1")).toBeInTheDocument();
    expect(screen.getByText("计划 2")).toBeInTheDocument();
  });

  it("warning 步骤以告警样式展示", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[makeStep({ status: "warning", title: "证据覆盖不足" })]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    const row = screen.getByText("证据覆盖不足").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-status", "warning");
  });

  it("failed 折叠文案为「处理失败」，展开后失败步骤可见", () => {
    render(
      <AgentExecutionTimeline
        status="failed"
        summary={null}
        steps={[makeStep({ status: "failed", title: "工具调用失败" })]}
      />
    );

    expect(screen.getByText("处理失败")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    const row = screen.getByText("工具调用失败").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-status", "failed");
  });

  it("cancelled 折叠文案为「已停止处理」，展开后取消步骤可见", () => {
    render(
      <AgentExecutionTimeline
        status="cancelled"
        summary={null}
        steps={[makeStep({ status: "cancelled", title: "生成被中断" })]}
      />
    );

    expect(screen.getByText("已停止处理")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    const row = screen.getByText("生成被中断").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-status", "cancelled");
  });

  it("折叠按钮 aria-expanded 可切换且可键盘操作", async () => {
    const user = userEvent.setup();
    render(
      <AgentExecutionTimeline
        status="completed"
        steps={[toolStep]}
        summary={completedSummary}
      />
    );

    const toggle = screen.getByRole("button", { name: /查看执行过程/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // 焦点在按钮上时按 Enter 等价于点击（jsdom 中真实键盘激活）
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("从 running 转为 completed 时自动折叠为单行摘要", () => {
    const { rerender } = render(
      <AgentExecutionTimeline
        status="running"
        steps={[makeStep({ status: "running", title: "正在查询数据" })]}
      />
    );
    expect(screen.getByText("正在查询数据…")).toBeInTheDocument();

    rerender(
      <AgentExecutionTimeline
        status="completed"
        steps={[toolStep]}
        summary={completedSummary}
      />
    );

    // 自动折叠：只保留单行摘要（icon + 文案 + 查看执行过程 + chevron），步骤与动态状态行均消失
    expect(screen.getByText("已完成 Agent 分析 · 1 次查询 · 6 条证据")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看执行过程/ })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(screen.queryByText("查询商品关联数据")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent 正在调用业务工具并核验证据")).not.toBeInTheDocument();
  });

  it("空 steps 不渲染任何内容（旧消息/旧后端向后兼容）", () => {
    const { container: emptyContainer } = render(
      <AgentExecutionTimeline status="completed" steps={[]} summary={null} />
    );
    expect(emptyContainer.firstChild).toBeNull();

    const { container: undefinedContainer } = render(
      <AgentExecutionTimeline status="running" summary={null} />
    );
    expect(undefinedContainer.firstChild).toBeNull();
  });
});
