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

  it("running 展开态：头部显示最后 running 步骤标题，只存在一条 running 步骤行（无重复状态卡）", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="running"
        steps={[
          makeStep({
            stepId: "plan-1-review--1",
            seq: 1,
            phase: "review",
            status: "running",
            title: "正在核验证据",
            detail: "比对商品关联证据"
          })
        ]}
      />
    );

    // 头部标题 = 最后 running 步骤标题（去句尾标点）+ 省略号，不再固定显示静态标题
    expect(screen.getByText("正在核验证据…")).toBeInTheDocument();
    expect(screen.queryByText("AI 处理过程")).not.toBeInTheDocument();
    // 只存在一条 running 步骤行（步骤标题本体），无独立状态卡
    expect(container.querySelectorAll('li[data-status="running"]')).toHaveLength(1);
    expect(screen.getAllByText("正在核验证据")).toHaveLength(1);
    expect(screen.queryByText("Agent 正在调用业务工具并核验证据")).not.toBeInTheDocument();
  });

  it("running 态无进行中步骤时头部回退为「正在分析并查询相关数据…」", () => {
    render(
      <AgentExecutionTimeline
        status="running"
        steps={[makeStep({ stepId: "plan-1-review--1", seq: 1, phase: "review" })]}
      />
    );

    expect(screen.getByText("正在分析并查询相关数据…")).toBeInTheDocument();
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

  it("running 截断只作用于计划步骤，全局 generation 步骤始终完整渲染", () => {
    render(
      <AgentExecutionTimeline
        status="running"
        summary={null}
        steps={[
          ...makeManySteps(8),
          makeStep({ stepId: "gen-1", seq: 9, phase: "generation", plan: 2, title: "正在生成回答" }),
          makeStep({
            stepId: "gen-2",
            seq: 10,
            phase: "generation",
            plan: 2,
            status: "running",
            title: "回答生成中"
          })
        ]}
      />
    );

    // 计划步骤仍只展示最近 5 步（seq 4~8），更早 3 步折叠
    for (const seq of [4, 5, 6, 7, 8]) {
      expect(screen.getByText(`步骤 ${seq}`)).toBeInTheDocument();
    }
    for (const seq of [1, 2, 3]) {
      expect(screen.queryByText(`步骤 ${seq}`)).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "已省略更早 3 步" })).toBeInTheDocument();
    // 全局 generation 步骤不受截断影响，始终完整渲染
    expect(screen.getByText("正在生成回答")).toBeInTheDocument();
    expect(screen.getByText("回答生成中")).toBeInTheDocument();
    // 头部标题取最后的 running 步骤（generation 阶段）
    expect(screen.getByText("回答生成中…")).toBeInTheDocument();
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

  it("completed 后默认折叠为一行摘要（含查询次数与核验证据数），不展示步骤", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        steps={[toolStep]}
        summary={completedSummary}
      />
    );

    expect(
      screen.getByText("已完成分析 · 1 次查询 · 核验 6 条证据")
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

  it("多计划时按 plan 分组展示「计划 N」标题，展开态头部为静态标题", () => {
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
    expect(screen.getByText("AI 处理过程")).toBeInTheDocument();
  });

  it("multi-plan：generation 作为全局阶段渲染在所有计划组之后，不挂在任何计划 chip 下", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({ stepId: "p1-a", seq: 1, plan: 1, phase: "planning", title: "计划一规划" }),
          makeStep({ stepId: "p1-b", seq: 2, plan: 1, phase: "tool", title: "计划一查询" }),
          makeStep({ stepId: "p1-c", seq: 3, plan: 1, phase: "review", title: "计划一核验" }),
          makeStep({ stepId: "p2-a", seq: 4, plan: 2, phase: "planning", title: "计划二规划" }),
          makeStep({ stepId: "p2-b", seq: 5, plan: 2, phase: "tool", title: "计划二查询" }),
          makeStep({ stepId: "p2-c", seq: 6, plan: 2, phase: "review", title: "计划二核验" }),
          makeStep({
            stepId: "gen-1",
            seq: 7,
            plan: 2,
            phase: "generation",
            status: "completed",
            title: "回答生成完成"
          })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看执行过程/ }));

    // DOM 顺序：计划 1 内容 → 计划 2 内容 → 回答生成完成
    const liTitles = Array.from(container.querySelectorAll("li")).map(
      (li) => li.querySelector("p")?.textContent
    );
    expect(liTitles).toEqual([
      "计划一规划",
      "计划一查询",
      "计划一核验",
      "计划二规划",
      "计划二查询",
      "计划二核验",
      "回答生成完成"
    ]);

    // generation 行不挂在任何「计划 N」chip 所在的计划组内
    const genGroup = screen.getByText("回答生成完成").closest("ul")?.parentElement;
    expect(genGroup).not.toBeNull();
    expect(genGroup!.textContent).not.toContain("计划 1");
    expect(genGroup!.textContent).not.toContain("计划 2");
    // 计划 chip 仍只有两组
    expect(screen.getAllByText(/^计划 \d$/)).toHaveLength(2);
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
    expect(screen.getByText("已完成分析 · 1 次查询 · 核验 6 条证据")).toBeInTheDocument();
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
