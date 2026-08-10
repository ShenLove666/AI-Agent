import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamHandlers } from "@/hooks/useStreamResponse";
import { disposeAgentProgressScheduler } from "@/utils/agentProgressPresentation";

const { createStreamResponseMock } = vi.hoisted(() => ({
  createStreamResponseMock: vi.fn()
}));

vi.mock("@/services/chatService", () => ({
  stopTask: vi.fn(),
  submitFeedback: vi.fn(),
  cancelFeedback: vi.fn(),
  generateRecommendedQuestions: vi.fn(),
  regenerateTurn: vi.fn()
}));

vi.mock("@/hooks/useStreamResponse", () => ({
  createStreamResponse: createStreamResponseMock
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() }
}));

import { useChatStore } from "./chatStore";

/** 捕获 createStreamResponse 收到的 handlers，供测试注入 agent_progress 事件。
 *  start 永不 resolve：模拟流式进行中，避免 runAssistantStream 的 finally
 *  清空 streamingMessageId 后注入的事件被忽略。 */
function setupCapturedHandlers() {
  let captured: StreamHandlers | undefined;
  createStreamResponseMock.mockImplementation((_opts: unknown, handlers: StreamHandlers) => {
    captured = handlers;
    return { start: vi.fn(() => new Promise(() => {})), cancel: vi.fn() };
  });
  return () => {
    if (!captured) throw new Error("createStreamResponse 未被调用");
    return captured;
  };
}

function toolProgress(
  seq: number,
  status: "running" | "completed",
  callId: string | undefined,
  plan = 1
) {
  return {
    seq,
    phase: "tool" as const,
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

describe("chatStore agent_progress（经 Presentation Scheduler）", () => {
  beforeEach(() => {
    createStreamResponseMock.mockReset();
    useChatStore.setState({
      messages: [],
      isStreaming: false,
      streamingMessageId: null,
      currentSessionId: null,
      isCreatingNew: false,
      thinkingStartAt: null,
      streamTaskId: null,
      streamAbort: null,
      cancelRequested: false,
      deepThinkingEnabled: false,
      knowledgeBaseIds: []
    });
    // 终态 reveal 依赖 minRunningVisibleMs（150ms）定时器
    vi.useFakeTimers();
    // scheduler 的 DEV 调试日志不参与断言，静音避免刷屏（源代码行为不改）
    vi.spyOn(console, "debug").mockImplementation(() => {});
  });

  afterEach(() => {
    // 释放本测试创建的消息级 scheduler（start 永不 resolve，finally 不会执行）
    const streamingMessageId = useChatStore.getState().streamingMessageId;
    if (streamingMessageId) disposeAgentProgressScheduler(streamingMessageId);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("同 plan 同工具不同 callId 各自成步，第二条 completed 按 callId 原地更新（running 先行，推进定时器后终态 reveal）", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中；
    // createStreamResponse 在 sendMessage 的同步段内被调用，返回时 handlers 已捕获
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    // 同一工具被调用两次：call-1 与 call-2 各成一步，stepId 不同
    handlers.onAgentProgress?.(toolProgress(1, "running", "call-1"));
    handlers.onAgentProgress?.(toolProgress(2, "running", "call-2"));

    let steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(2);
    expect(steps[0].stepId).toBe("plan-1-tool-call-1");
    expect(steps[1].stepId).toBe("plan-1-tool-call-2");
    expect(steps[0].stepId).not.toBe(steps[1].stepId);
    expect(steps[0].tool?.callId).toBe("call-1");
    expect(steps[1].tool?.callId).toBe("call-2");

    // 第二条调用 completed：终态被 hold（running 先行），推进 minRunningVisibleMs 后原地更新
    handlers.onAgentProgress?.(toolProgress(3, "completed", "call-2"));

    steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(2);
    expect(steps[1].status).toBe("running");

    vi.advanceTimersByTime(200);
    steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(2);
    expect(steps[1].stepId).toBe("plan-1-tool-call-2");
    expect(steps[1].status).toBe("completed");
    // 第一条 running 不受影响
    expect(steps[0].stepId).toBe("plan-1-tool-call-1");
    expect(steps[0].status).toBe("running");
  });

  it("同 plan 同工具不同 callId 且 callId 跨 plan 复用时按 plan 隔离", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    handlers.onAgentProgress?.(toolProgress(1, "running", "call-1", 1));
    handlers.onAgentProgress?.(toolProgress(2, "running", "call-2", 1));
    // 新 plan 里又调用 call-1（callId 全局唯一，此处仅验证 plan 隔离不合并）
    handlers.onAgentProgress?.(toolProgress(3, "running", "call-3", 2));

    const steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(3);
    expect(steps.map((step) => step.stepId)).toEqual([
      "plan-1-tool-call-1",
      "plan-1-tool-call-2",
      "plan-2-tool-call-3"
    ]);
  });

  it("旧后端无 callId：保持按 (plan, phase, toolName) 合并的兼容行为", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    // 无 callId 的 running→completed 同 key 事件合并为一条
    handlers.onAgentProgress?.(toolProgress(1, "running", undefined));
    // 终态先被 hold：仍是 running 一行
    handlers.onAgentProgress?.(toolProgress(2, "completed", undefined));

    let steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("running");
    expect(steps[0].stepId).toBe("plan-1-tool-commerce_search_association_rules-1");

    vi.advanceTimersByTime(200);
    steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("completed");
    expect(steps[0].stepId).toBe("plan-1-tool-commerce_search_association_rules-1");
  });

  it("phase=complete 收尾：pending 收敛 + 仍 running 的步骤立即 finalize 为 completed（无需推进定时器）", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    handlers.onAgentProgress?.(toolProgress(1, "running", "call-1"));
    handlers.onAgentProgress?.(toolProgress(2, "running", "call-2"));
    // call-1 的 completed 被 hold（running 先行）
    handlers.onAgentProgress?.(toolProgress(3, "completed", "call-1"));
    expect(useChatStore.getState().messages[1].agentSteps![0].status).toBe("running");

    // complete 是收尾标记：不创建步骤，一次性收敛
    handlers.onAgentProgress?.({
      seq: 4,
      phase: "complete",
      status: "completed",
      title: "完成"
    });

    const steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(2);
    expect(steps[0].status).toBe("completed");
    expect(steps[1].status).toBe("completed");
    expect(steps[0].stepId).toBe("plan-1-tool-call-1");
    expect(steps[1].stepId).toBe("plan-1-tool-call-2");

    // 定时器已清空：推进时间不再有变化
    const before = useChatStore.getState().messages[1].agentSteps;
    vi.advanceTimersByTime(300);
    expect(useChatStore.getState().messages[1].agentSteps).toBe(before);
  });

  it("planning completed 携带 mode=direct：消息写入 agentExecutionMode", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("直接问一个问题");
    const handlers = getHandlers();

    handlers.onAgentProgress?.({
      seq: 1,
      phase: "planning",
      status: "completed",
      title: "制定计划",
      mode: "direct"
    });

    expect(useChatStore.getState().messages[1].agentExecutionMode).toBe("direct");
  });

  it("complete 携带 terminal=refused：消息写入 agentTerminalState", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    handlers.onAgentProgress?.({
      seq: 1,
      phase: "complete",
      status: "completed",
      title: "完成",
      terminal: "refused"
    });

    const message = useChatStore.getState().messages[1];
    expect(message.agentTerminalState).toBe("refused");
    // terminal 只写 agentTerminalState，不污染 agentSteps / agentExecutionMode
    expect(message.agentSteps).toEqual([]);
    expect(message.agentExecutionMode).toBeUndefined();
  });

  it("planning completed 无 mode / complete 无 terminal：不写对应字段（旧后端兼容）", () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    handlers.onAgentProgress?.({
      seq: 1,
      phase: "planning",
      status: "completed",
      title: "制定计划"
    });
    handlers.onAgentProgress?.({
      seq: 2,
      phase: "complete",
      status: "completed",
      title: "完成"
    });

    const message = useChatStore.getState().messages[1];
    expect(message.agentExecutionMode).toBeUndefined();
    expect(message.agentTerminalState).toBeUndefined();
  });
});
