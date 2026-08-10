import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MessageItem } from "./MessageItem";
import { useChatStore } from "@/stores/chatStore";
import type { AgentExecutionStep, Message } from "@/types";

const steps: AgentExecutionStep[] = [
  {
    stepId: "plan-1-tool-call-1",
    seq: 1,
    phase: "tool",
    status: "completed",
    plan: 1,
    title: "业务数据查询",
    tool: { name: "t", label: "工具A", status: "completed" }
  }
];

const runningSteps: AgentExecutionStep[] = [
  {
    stepId: "plan-1-tool-call-1",
    seq: 1,
    phase: "tool",
    status: "running",
    plan: 1,
    title: "业务数据查询",
    tool: { name: "t", label: "工具A", status: "running" }
  }
];

const summary = { planCount: 1, toolCallCount: 1, evidenceCount: 1, replanCount: 0 };

/** message 层带执行记录（当前版本），v1 老版本无任何 Timeline 数据 */
function makeVersionedMessage(): Message {
  return {
    id: "parent-msg",
    role: "assistant",
    content: "当前版本答案",
    status: "done",
    messageStatus: "NORMAL",
    version: 2,
    agentSteps: steps,
    agentExecutionStatus: "completed",
    agentExecutionSummary: summary,
    answerVersions: [
      {
        id: "v1",
        version: 1,
        content: "旧版本答案",
        messageStatus: "NORMAL"
        // 老版本无 agentSteps / agentExecutionStatus / agentExecutionSummary
      },
      {
        id: "v2",
        version: 2,
        content: "当前版本答案",
        messageStatus: "NORMAL",
        agentSteps: steps,
        agentExecutionStatus: "completed",
        agentExecutionSummary: summary
      }
    ]
  };
}

// AgentExecutionTimeline 的 section aria-label 前后端同步推进中有两种措辞
// （"Agent 执行过程" / "AI 处理过程"），断言对两种都兼容
function queryTimelineSection(container: HTMLElement): HTMLElement | null {
  return container.querySelector(
    'section[aria-label="Agent 执行过程"], section[aria-label="AI 处理过程"]'
  );
}

describe("MessageItem 版本严格绑定 Agent Timeline", () => {
  beforeEach(() => {
    useChatStore.setState({ isLoading: false });
  });

  afterEach(cleanup);

  it("默认选中 message.version 对应版本（带执行记录）时渲染 Timeline", () => {
    const { container } = render(<MessageItem message={makeVersionedMessage()} />);

    // v2 选中：Timeline 挂载（折叠为单行摘要）
    expect(queryTimelineSection(container)).not.toBeNull();
    expect(screen.getByText(/已完成分析/)).toBeInTheDocument();
  });

  it("切到无 Timeline 数据的老版本时不渲染 Timeline（不回退到 message 层执行记录）", () => {
    const { container } = render(<MessageItem message={makeVersionedMessage()} />);

    // 切到 v1（无 agentSteps）：Timeline 完全不渲染，绝不串显当前版本的执行过程
    fireEvent.click(screen.getByRole("button", { name: "上一版答案" }));
    expect(queryTimelineSection(container)).toBeNull();
    expect(screen.queryByText(/已完成分析/)).not.toBeInTheDocument();

    // 切回 v2：Timeline 恢复
    fireEvent.click(screen.getByRole("button", { name: "下一版答案" }));
    expect(queryTimelineSection(container)).not.toBeNull();
  });

  it("无 answerVersions 时直接使用 message 自身执行记录（不受影响）", () => {
    const message: Message = {
      id: "plain-msg",
      role: "assistant",
      content: "答案",
      status: "done",
      messageStatus: "NORMAL",
      agentSteps: steps,
      agentExecutionStatus: "completed",
      agentExecutionSummary: summary
    };
    const { container } = render(<MessageItem message={message} />);

    expect(queryTimelineSection(container)).not.toBeNull();
  });

  it("助手头部文案为「邻里鲜选 AI 助手」，不渲染 AI 徽标", () => {
    const { container } = render(<MessageItem message={makeVersionedMessage()} />);

    expect(screen.getByText("邻里鲜选 AI 助手")).toBeInTheDocument();
    // AI 身份强调只由 Timeline 的 Sparkles 承担，不再有独立徽标
    expect(screen.queryByText("AI 辅助")).not.toBeInTheDocument();
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
    expect(container.querySelector(".ai-wait")).toBeNull();
  });

  it("streaming 且已有 agentSteps 时不再渲染等待点（Timeline 已在实时执行）", () => {
    const message: Message = {
      id: "stream-msg",
      role: "assistant",
      content: "",
      status: "streaming",
      messageStatus: "NORMAL",
      agentSteps: runningSteps,
      agentExecutionStatus: "running"
    };
    const { container } = render(<MessageItem message={message} />);

    expect(container.querySelector(".ai-wait")).toBeNull();
  });

  it("streaming 且尚无 agentSteps 时仍渲染等待点", () => {
    const message: Message = {
      id: "stream-msg",
      role: "assistant",
      content: "",
      status: "streaming",
      messageStatus: "NORMAL"
    };
    const { container } = render(<MessageItem message={message} />);

    expect(container.querySelector(".ai-wait")).not.toBeNull();
  });

  it("isLatestTurn 透传：最新轮执行时 Timeline 展开，非最新轮默认折叠", () => {
    const message: Message = {
      id: "stream-msg",
      role: "assistant",
      content: "",
      status: "streaming",
      messageStatus: "NORMAL",
      agentSteps: runningSteps,
      agentExecutionStatus: "running"
    };
    const { container, rerender } = render(<MessageItem message={message} />);

    // 默认 isLatestTurn=true：最新轮执行 → 展开（头部显示动态活动标题）
    expect(queryTimelineSection(container)).not.toBeNull();
    expect(screen.getByText("正在查询工具A…")).toBeInTheDocument();

    rerender(<MessageItem message={message} isLatestTurn={false} />);

    expect(screen.queryByText("正在查询工具A…")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看处理过程/ })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
  });
});
