import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { raiseSupportEscalation } from "@/services/supportService";
import { SupportWorkbenchPage } from "./SupportWorkbenchPage";

const fixtures = vi.hoisted(() => ({
  internalFact: "内部订单事实：支付流水已进入人工复核队列",
  suggestionStatus: "completed",
  reply: Array.from(
    { length: 40 },
    (_, index) => `第 ${index + 1} 条对客说明：请保留凭证申请售后。`
  ).join("\n")
}));

vi.mock("@/services/supportService", () => ({
  getSupportCases: vi.fn().mockResolvedValue([
    {
      id: 3,
      caseKey: "demo-3",
      customerName: "顾客",
      channel: "web",
      subject: "退款咨询",
      status: "pending",
      priority: "urgent",
      assigneeId: null,
      labels: ["refund"],
      unread: true,
      version: 1,
      isDemo: true,
      lastMessage: "优惠券会退吗",
      updatedAt: "2026-08-07T00:00:00"
    }
  ]),
  getSupportMetrics: vi.fn().mockResolvedValue({
    totalCases: 1,
    pendingCases: 1,
    resolvedCases: 0,
    escalatedCases: 0,
    resolutionRate: 0,
    acceptanceRate: null,
    editRate: null,
    citationCoverage: 100,
    provenance: "demo"
  }),
  getSupportWorkspace: vi.fn().mockResolvedValue({
    case: { id: 3 },
    order: null,
    activeSuggestion: null,
    outboundMessages: [],
    diagnostics: { messageCount: 1, suggestionCount: 1, outboundCount: 0 }
  }),
  getSupportCase: vi.fn().mockImplementation(() =>
    Promise.resolve({
    id: 3,
    caseKey: "demo-3",
    customerName: "顾客",
    channel: "web",
    subject: "退款咨询",
    status: "pending",
    priority: "urgent",
    assigneeId: null,
    labels: ["refund"],
    unread: true,
    version: 1,
    isDemo: true,
    lastMessage: "优惠券会退吗",
    updatedAt: "2026-08-07T00:00:00",
    resolutionCode: null,
    resolutionNote: null,
    messages: [
      {
        id: 3,
        role: "customer",
        content: "优惠券会退吗",
        sentToCustomer: false,
        suggestionId: null,
        createdAt: "2026-08-07T00:00:00"
      }
    ],
    events: [],
    suggestions: [
      {
        id: 7,
        status: fixtures.suggestionStatus,
        content: fixtures.reply,
        citations: [{ content: "优惠券按活动规则返还", releaseVersion: "v1" }],
        riskFlags: fixtures.suggestionStatus === "completed" ? ["refund_review"] : [],
        modelId: "deepseek-flash",
        promptVersion: "support-v1",
        knowledgeReleaseId: 1,
        latencyMs: 620,
        errorCode: null,
        runtimeMode: "live",
        terminalState: "needs_review",
        resolution: {
          intent: "refund_status",
          risk: "high",
          facts: [{ type: "order", content: fixtures.internalFact, orderNo: "ORDER-3" }],
          missingFacts: ["优惠券返还的具体到账时间"],
          recommendedActions: ["发送前核对活动返还规则"],
          draftReply: "内部草稿，不应覆盖已生成的对客建议",
          citations: ["内部知识片段"],
          canSend: false,
          escalationReason: "退款状态需要人工复核",
          terminalState: "needs_review"
        },
        decision: null,
        finalContent: null,
        createdAt: "2026-08-07T00:00:00"
      }
      ]
    })
  ),
  assignSupportCase: vi.fn(),
  transitionSupportCase: vi.fn(),
  sendManualReply: vi.fn(),
  generateSupportSuggestion: vi.fn(),
  decideSupportSuggestion: vi.fn(),
  raiseSupportEscalation: vi.fn()
}));

afterEach(() => {
  cleanup();
  fixtures.suggestionStatus = "completed";
  vi.clearAllMocks();
});

describe("ReplyCopilot", () => {
  it("keeps every workbench pane reachable when zoom narrows the viewport", async () => {
    render(<SupportWorkbenchPage />);

    await screen.findByRole("textbox", { name: "可编辑的对客回复" });

    const workbench = screen.getByRole("region", { name: "客服处理工作区" });
    const queue = screen.getByRole("region", { name: "工单队列" });
    const conversation = screen.getByRole("region", { name: "工单对话" });
    const copilot = screen.getByRole("region", { name: "AI 回复助手" });

    expect(workbench).toHaveClass("h-auto", "min-h-0", "overflow-visible");
    expect(workbench).toHaveClass(
      "xl:h-[calc(100dvh-240px)]",
      "xl:min-h-[560px]",
      "xl:overflow-hidden"
    );
    expect(queue).toHaveClass("min-h-[420px]", "xl:min-h-0");
    expect(conversation).toHaveClass("min-h-[640px]", "xl:min-h-0");
    expect(copilot).toHaveClass("min-h-[680px]", "xl:min-h-0");
  });

  it("keeps review actions reachable outside the independently scrolling long reply", async () => {
    render(<SupportWorkbenchPage />);

    const editor = await screen.findByRole("textbox", { name: "可编辑的对客回复" });
    const body = screen.getByRole("region", { name: "AI 回复建议正文" });
    const actions = screen.getByRole("region", { name: "AI 回复建议操作" });

    expect(editor).toHaveValue(fixtures.reply);
    expect(editor).toHaveClass("max-h-[240px]", "overflow-y-auto");
    expect(body).toHaveClass("min-h-0", "flex-1", "overflow-y-auto");
    expect(within(body).queryByRole("button", { name: "采纳并发送" })).not.toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "采纳并发送" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "升级主管" })).toBeInTheDocument();

    fireEvent.change(editor, { target: { value: "已人工修订的对客回复" } });

    expect(within(body).queryByRole("button", { name: "发送修订版" })).not.toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "发送修订版" })).toBeInTheDocument();
  });

  it("keeps cited evidence collapsed until the reviewer asks to inspect it", async () => {
    render(<SupportWorkbenchPage />);

    const evidenceToggle = await screen.findByRole("button", { name: "处理依据" });

    expect(evidenceToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("优惠券按活动规则返还")).not.toBeInTheDocument();

    fireEvent.click(evidenceToggle);

    expect(evidenceToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("优惠券按活动规则返还")).toBeInTheDocument();
  });

  it("summarizes resolution guidance without copying internal evidence into the customer reply", async () => {
    render(<SupportWorkbenchPage />);

    const editor = await screen.findByRole("textbox", { name: "可编辑的对客回复" });
    const summary = screen.getByRole("region", { name: "AI 处理建议" });

    expect(within(summary).getByText("高")).toBeInTheDocument();
    expect(within(summary).getByText("优惠券返还的具体到账时间")).toBeInTheDocument();
    expect(within(summary).getByText("发送前核对活动返还规则")).toBeInTheDocument();
    expect((editor as HTMLTextAreaElement).value).not.toContain(fixtures.internalFact);
    expect((editor as HTMLTextAreaElement).value).not.toContain("内部知识片段");
    expect((editor as HTMLTextAreaElement).value).not.toContain("内部草稿");
  });

  it("offers only supervisor escalation in the fixed action bar when evidence is insufficient", async () => {
    fixtures.suggestionStatus = "insufficient_evidence";
    render(<SupportWorkbenchPage />);

    expect(await screen.findByText("AI 建议暂不可用")).toBeInTheDocument();
    const actions = screen.getByRole("region", { name: "AI 回复建议操作" });

    expect(within(actions).queryByRole("button", { name: /发送/ })).not.toBeInTheDocument();

    fireEvent.click(within(actions).getByRole("button", { name: "升级主管" }));

    await waitFor(() =>
      expect(raiseSupportEscalation).toHaveBeenCalledWith(
        3,
        expect.objectContaining({ category: "agent_insufficient_evidence" })
      )
    );
  });
});
