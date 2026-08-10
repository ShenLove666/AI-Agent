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

const runningToolStep = makeStep({
  stepId: "plan-1-tool-1",
  seq: 1,
  phase: "tool",
  status: "running",
  title: "业务数据查询",
  tool: { name: "a", label: "商品关联分析", status: "running" }
});

describe("AgentExecutionTimeline", () => {
  afterEach(() => {
    cleanup();
  });

  it("单轮完成态：planning/tool×2/review/generation 全部渲染，tool 名称只出现一次，generation 在最后且无子标题", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({ stepId: "plan-1-planning-1", seq: 1, phase: "planning", title: "制定查询计划" }),
          makeStep({
            stepId: "plan-1-tool-1",
            seq: 2,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "a", label: "商品关联分析", status: "completed", durationMs: 14, evidenceCount: 6 }
          }),
          makeStep({
            stepId: "plan-1-tool-2",
            seq: 3,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "b", label: "商品销量查询", status: "completed", durationMs: 8, evidenceCount: 3 }
          }),
          makeStep({ stepId: "plan-1-review-1", seq: 4, phase: "review", title: "核验证据" }),
          makeStep({ stepId: "plan-1-generation-1", seq: 5, phase: "generation", title: "回答生成完成" })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看处理过程/ }));

    expect(screen.getByText("制定查询计划")).toBeInTheDocument();
    // tool 名称只出现一次（无嵌套工具卡重复）
    expect(screen.getAllByText("商品关联分析")).toHaveLength(1);
    expect(screen.getAllByText("商品销量查询")).toHaveLength(1);
    expect(screen.getByText("核验证据")).toBeInTheDocument();
    // 耗时右对齐展示；证据数并入 detail，不重复出现
    expect(screen.getByText("14ms")).toBeInTheDocument();
    expect(screen.getByText("8ms")).toBeInTheDocument();
    expect(screen.getByText("找到 6 条相关数据")).toBeInTheDocument();
    expect(screen.getByText("找到 3 条相关数据")).toBeInTheDocument();
    // generation 行无子标题（不出现「回答生成」标签），且在最后
    expect(screen.queryByText("回答生成")).not.toBeInTheDocument();
    const lis = container.querySelectorAll("li");
    expect(lis[lis.length - 1].textContent).toContain("回答生成完成");
  });

  it("evidenceCount=0：显示「暂未找到有效数据」，关联工具显示「暂未找到有效关联数据」，不出现 0 条证据", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({
            stepId: "t-1",
            seq: 1,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "a", label: "商品销量查询", status: "completed", evidenceCount: 0 }
          }),
          makeStep({
            stepId: "t-2",
            seq: 2,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "b", label: "商品关联分析", status: "completed", evidenceCount: 0 }
          })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看处理过程/ }));

    expect(screen.getByText("暂未找到有效数据")).toBeInTheDocument();
    expect(screen.getByText("暂未找到有效关联数据")).toBeInTheDocument();
    expect(screen.queryByText(/0 条证据/)).not.toBeInTheDocument();
  });

  it("replan 合并：review warning + 紧随 replan → 只有一行「数据不足，已调整查询策略」", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({
            stepId: "plan-1-review-1",
            seq: 1,
            phase: "review",
            status: "warning",
            title: "证据覆盖不足"
          }),
          makeStep({ stepId: "plan-1-replan-1", seq: 2, phase: "replan", title: "调整查询策略" })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看处理过程/ }));

    expect(screen.getByText("数据不足，已调整查询策略")).toBeInTheDocument();
    expect(screen.getByText("正在补充查询其他数据来源")).toBeInTheDocument();
    expect(screen.queryByText("证据覆盖不足")).not.toBeInTheDocument();
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });

  it("escalate：review warning 无紧随 replan → 独立成行（告警样式）", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({
            stepId: "plan-1-review-1",
            seq: 1,
            phase: "review",
            status: "warning",
            title: "数据不足，已转人工"
          })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看处理过程/ }));

    const row = screen.getByText("数据不足，已转人工").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-status", "warning");
  });

  it("多轮：plan 1 压缩为一条 round-summary，点击「查看详情」展开该轮，generation 仍在最后", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        steps={[
          makeStep({ stepId: "p1-planning", seq: 1, plan: 1, phase: "planning", title: "制定计划" }),
          makeStep({
            stepId: "p1-tool-1",
            seq: 2,
            plan: 1,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "a", label: "商品销量查询", status: "completed", evidenceCount: 0 }
          }),
          makeStep({
            stepId: "p1-tool-2",
            seq: 3,
            plan: 1,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "b", label: "商品画像查询", status: "completed", evidenceCount: 0 }
          }),
          makeStep({
            stepId: "p2-planning",
            seq: 4,
            plan: 2,
            phase: "planning",
            title: "重新制定计划"
          }),
          makeStep({
            stepId: "p2-tool-1",
            seq: 5,
            plan: 2,
            phase: "tool",
            title: "业务数据查询",
            tool: { name: "c", label: "购物篮关联规则", status: "completed", evidenceCount: 3 }
          }),
          makeStep({ stepId: "gen-1", seq: 6, plan: 2, phase: "generation", title: "回答生成完成" })
        ]}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /查看处理过程/ }));

    // plan 1 压缩为摘要行，plan 2 完整展示，generation 在最后
    expect(
      screen.getByText("第一轮查询完成 · 2 项数据源 · 暂无有效结果")
    ).toBeInTheDocument();
    expect(screen.queryByText("制定计划")).not.toBeInTheDocument();
    expect(screen.getByText("重新制定计划")).toBeInTheDocument();
    let lis = container.querySelectorAll("li");
    expect(lis[lis.length - 1].textContent).toContain("回答生成完成");

    // 点击「查看详情」展开 plan 1
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));

    expect(screen.getByText("制定计划")).toBeInTheDocument();
    expect(screen.getByText("商品销量查询")).toBeInTheDocument();
    expect(screen.queryByText(/第一轮查询完成/)).not.toBeInTheDocument();
    lis = container.querySelectorAll("li");
    expect(lis[lis.length - 1].textContent).toContain("回答生成完成");
  });

  it("运行中：header 显示 currentActivityTitle，运行步骤行为 running 图标", () => {
    render(<AgentExecutionTimeline status="running" summary={null} steps={[runningToolStep]} />);

    expect(screen.getByText("正在查询商品关联分析…")).toBeInTheDocument();
    const row = screen.getByText("商品关联分析").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-status", "running");
  });

  it("完成不自动折叠：status running→completed 后仍保持展开", () => {
    const { rerender } = render(
      <AgentExecutionTimeline status="running" summary={null} steps={[runningToolStep]} />
    );
    expect(screen.getByText("正在查询商品关联分析…")).toBeInTheDocument();

    rerender(
      <AgentExecutionTimeline status="completed" steps={[toolStep]} summary={completedSummary} />
    );

    // 仍展开：header 为静态标题，步骤行与耗时可见，无折叠按钮
    expect(screen.getByText("AI 处理过程")).toBeInTheDocument();
    expect(screen.getByText("商品关联分析")).toBeInTheDocument();
    expect(screen.getByText("14ms")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /查看处理过程/ })).not.toBeInTheDocument();
  });

  it("isCurrentTurn 生命周期：false→true 展开、true→false 收起；历史（非最新轮）默认折叠", () => {
    const steps = [
      makeStep({
        stepId: "t-1",
        seq: 1,
        phase: "tool",
        title: "业务数据查询",
        tool: { name: "a", label: "商品销量查询", status: "completed", evidenceCount: 2 }
      })
    ];
    const { rerender } = render(
      <AgentExecutionTimeline
        status="completed"
        steps={steps}
        summary={null}
        isCurrentTurn={false}
      />
    );

    // 历史会话默认折叠
    expect(screen.getByRole("button", { name: /查看处理过程/ })).toHaveAttribute(
      "aria-expanded",
      "false"
    );

    // false → true：展开
    rerender(
      <AgentExecutionTimeline
        status="completed"
        steps={steps}
        summary={null}
        isCurrentTurn={true}
      />
    );
    expect(screen.getByText("商品销量查询")).toBeInTheDocument();

    // true → false：收起
    rerender(
      <AgentExecutionTimeline
        status="completed"
        steps={steps}
        summary={null}
        isCurrentTurn={false}
      />
    );
    expect(screen.queryByText("商品销量查询")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看处理过程/ })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
  });

  it("折叠态：显示 summaryText 与「查看处理过程」", () => {
    render(
      <AgentExecutionTimeline status="completed" steps={[toolStep]} summary={completedSummary} />
    );

    expect(screen.getByText("已完成分析 · 1 次查询 · 核验 6 条证据")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看处理过程/ })).toBeInTheDocument();
  });

  it("展开态头部右侧无 AI 徽标", () => {
    render(<AgentExecutionTimeline status="running" summary={null} steps={[runningToolStep]} />);

    expect(screen.getByText("正在查询商品关联分析…")).toBeInTheDocument();
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
  });

  it("折叠按钮 aria-expanded 可切换且可键盘操作", async () => {
    const user = userEvent.setup();
    render(
      <AgentExecutionTimeline status="completed" steps={[toolStep]} summary={completedSummary} />
    );

    const toggle = screen.getByRole("button", { name: /查看处理过程/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // 焦点在按钮上时按 Enter 等价于点击（jsdom 中真实键盘激活）
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("无内部滚动容器：时间线不在组件内创建 overflow-y-auto 元素", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="running"
        summary={null}
        steps={[
          runningToolStep,
          makeStep({ stepId: "t-2", seq: 2, phase: "review", status: "completed", title: "核验证据" })
        ]}
      />
    );

    expect(container.querySelector('[class*="overflow-y-auto"]')).toBeNull();
    expect(container.querySelector('[class*="overflow-auto"]')).toBeNull();
  });

  it("intent=history_reference 且无工具步骤：不渲染（隐藏 AI 处理过程）", () => {
    const { container } = render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        intent="history_reference"
        steps={[
          makeStep({ stepId: "plan-1-planning-1", seq: 1, phase: "planning", title: "制定计划" }),
          makeStep({ stepId: "plan-1-generation-1", seq: 2, phase: "generation", title: "生成回答" })
        ]}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("intent=refuse 无工具步骤：渲染折叠态并显示拒绝文案", () => {
    render(
      <AgentExecutionTimeline
        status="completed"
        summary={null}
        intent="refuse"
        steps={[
          makeStep({ stepId: "plan-1-planning-1", seq: 1, phase: "planning", title: "制定计划" }),
          makeStep({ stepId: "plan-1-generation-1", seq: 2, phase: "generation", title: "生成回答" })
        ]}
      />
    );
    expect(screen.getByText("该请求无法协助执行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看处理过程/ })).toBeInTheDocument();
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
