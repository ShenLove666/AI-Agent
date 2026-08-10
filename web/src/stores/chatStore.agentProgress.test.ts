import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamHandlers } from "@/hooks/useStreamResponse";

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

describe("chatStore agent_progress stepId 构造（callId 契约）", () => {
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
  });

  it("同 plan 同工具不同 callId 各自成步，第二条 completed 按 callId 原地更新", async () => {
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

    // 第二条调用 completed：共享 callId 原地更新，仍保持两条
    handlers.onAgentProgress?.(toolProgress(3, "completed", "call-2"));

    steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(2);
    expect(steps[1].stepId).toBe("plan-1-tool-call-2");
    expect(steps[1].status).toBe("completed");
    // 第一条 running 不受影响
    expect(steps[0].stepId).toBe("plan-1-tool-call-1");
    expect(steps[0].status).toBe("running");
  });

  it("同 plan 同工具不同 callId 且 callId 跨 plan 复用时按 plan 隔离", async () => {
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

  it("旧后端无 callId：保持按 (plan, phase, toolName) 合并的兼容行为", async () => {
    const getHandlers = setupCapturedHandlers();
    // 不 await：流式 start 永不 resolve，sendMessage 保持进行中
    useChatStore.getState().sendMessage("查询商品关联数据");
    const handlers = getHandlers();

    // 无 callId 的 running→completed 同 key 事件合并为一条
    handlers.onAgentProgress?.(toolProgress(1, "running", undefined));
    handlers.onAgentProgress?.(toolProgress(2, "completed", undefined));

    const steps = useChatStore.getState().messages[1].agentSteps!;
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("completed");
    expect(steps[0].stepId).toBe(
      "plan-1-tool-commerce_search_association_rules-1"
    );
  });
});
