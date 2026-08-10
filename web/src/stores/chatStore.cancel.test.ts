import { beforeEach, describe, expect, it, vi } from "vitest";

const { stopTaskRequest, streamAbortMock } = vi.hoisted(() => ({
  stopTaskRequest: vi.fn(),
  streamAbortMock: vi.fn()
}));

vi.mock("@/services/chatService", () => ({
  stopTask: stopTaskRequest,
  submitFeedback: vi.fn(),
  cancelFeedback: vi.fn(),
  generateRecommendedQuestions: vi.fn(),
  regenerateTurn: vi.fn()
}));

vi.mock("@/hooks/useStreamResponse", () => ({
  createStreamResponse: vi.fn(() => ({ start: vi.fn(), cancel: streamAbortMock }))
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() }
}));

import { useChatStore } from "./chatStore";

const streamingMessage = {
  id: "assistant-1",
  role: "assistant" as const,
  content: "正在生成…",
  status: "streaming" as const,
  isThinking: true,
  agentSteps: [
    {
      stepId: "plan-1-planning-1",
      seq: 1,
      phase: "planning" as const,
      status: "completed" as const,
      plan: 1,
      title: "制定计划"
    },
    {
      stepId: "plan-1-tool-2",
      seq: 2,
      phase: "tool" as const,
      status: "running" as const,
      plan: 1,
      title: "业务数据查询"
    }
  ],
  agentExecutionStatus: "running" as const
};

describe("chatStore cancelGeneration", () => {
  beforeEach(() => {
    stopTaskRequest.mockReset().mockResolvedValue(undefined);
    streamAbortMock.mockReset();
    useChatStore.setState({
      isStreaming: true,
      streamingMessageId: "assistant-1",
      streamTaskId: "task-1",
      streamAbort: streamAbortMock,
      cancelRequested: false,
      messages: [streamingMessage]
    });
  });

  it("finalizes the message locally, stops the task, and aborts the SSE connection", () => {
    useChatStore.getState().cancelGeneration();

    expect(stopTaskRequest).toHaveBeenCalledWith("task-1");
    expect(streamAbortMock).toHaveBeenCalledTimes(1);

    const message = useChatStore.getState().messages[0];
    expect(message.status).toBe("cancelled");
    expect(message.messageStatus).toBe("INTERRUPTED");
    expect(message.isThinking).toBe(false);
    expect(message.agentExecutionStatus).toBe("cancelled");
    expect(message.agentSteps?.[1].status).toBe("cancelled");
    // 已完成步骤不受影响
    expect(message.agentSteps?.[0].status).toBe("completed");
  });

  it("does not abort or stop anything when not streaming", () => {
    useChatStore.setState({ isStreaming: false });

    useChatStore.getState().cancelGeneration();

    expect(stopTaskRequest).not.toHaveBeenCalled();
    expect(streamAbortMock).not.toHaveBeenCalled();
  });
});
