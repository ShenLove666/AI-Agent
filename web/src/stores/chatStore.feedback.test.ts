import { beforeEach, describe, expect, it, vi } from "vitest";

const { submitFeedbackRequest, cancelFeedbackRequest } = vi.hoisted(() => ({
  submitFeedbackRequest: vi.fn(),
  cancelFeedbackRequest: vi.fn()
}));

vi.mock("@/services/chatService", () => ({
  stopTask: vi.fn(),
  submitFeedback: submitFeedbackRequest,
  cancelFeedback: cancelFeedbackRequest,
  generateRecommendedQuestions: vi.fn(),
  regenerateTurn: vi.fn()
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() }
}));

import { useChatStore } from "./chatStore";

const versionedMessage = {
  id: "parent-message",
  role: "assistant" as const,
  content: "active answer",
  status: "done" as const,
  feedback: "like" as const,
  answerVersions: [
    {
      id: "42",
      version: 1,
      content: "active answer",
      feedback: "like" as const,
      messageStatus: "NORMAL" as const
    }
  ]
};

describe("chatStore feedback", () => {
  beforeEach(() => {
    submitFeedbackRequest.mockReset().mockResolvedValue(undefined);
    cancelFeedbackRequest.mockReset().mockResolvedValue(undefined);
    useChatStore.setState({ messages: [versionedMessage] });
  });

  it("cancels feedback on the selected answer version and updates its visible state", async () => {
    await useChatStore.getState().submitFeedback("42", null);

    expect(cancelFeedbackRequest).toHaveBeenCalledWith("42");
    expect(useChatStore.getState().messages[0].answerVersions?.[0].feedback).toBeNull();
  });

  it("rolls the selected answer version back when persistence fails", async () => {
    submitFeedbackRequest.mockRejectedValueOnce(new Error("failed"));

    await useChatStore.getState().submitFeedback("42", "dislike");
    expect(useChatStore.getState().messages[0].answerVersions?.[0].feedback).toBe("like");
  });
});
