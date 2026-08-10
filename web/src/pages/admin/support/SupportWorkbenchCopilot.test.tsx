import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { decideSupportSuggestion } from "@/services/supportService";
import { SupportWorkbenchPage } from "./SupportWorkbenchPage";

const fixtures = vi.hoisted(() => ({
  risk: "low" as "low" | "medium" | "high",
  withSuggestion: true,
  citationGroups: null as null | {
    orderFacts: Array<{ type: string; content: string }>;
    rules: Array<{ content: string }>;
  },
  generateResolvers: [] as Array<(value: unknown) => void>
}));

const suggestion = () => {
  const resolution: Record<string, unknown> = {
    intent: "refund_status",
    risk: fixtures.risk,
    facts: [{ type: "order", content: "订单已支付 128.00 元" }],
    missingFacts: ["退款到账时间待确认"],
    recommendedActions: ["按退款规则核对后回复"],
    draftReply: "内部草稿，不应覆盖已生成的对客建议",
    citations: ["退款政策片段"],
    canSend: false,
    escalationReason: null,
    terminalState: "needs_review"
  };
  if (fixtures.citationGroups) resolution.citationGroups = fixtures.citationGroups;
  return {
    id: 7,
    status: "completed",
    content: "已为您确认退款政策，预计 3-5 个工作日到账。",
    citations: [{ content: "退款政策片段", releaseVersion: "v1" }],
    riskFlags: [],
    modelId: "deepseek-flash",
    promptVersion: "support-v1",
    knowledgeReleaseId: 1,
    latencyMs: 620,
    errorCode: null,
    runtimeMode: "live",
    terminalState: "needs_review",
    resolution,
    decision: null,
    finalContent: null,
    createdAt: "2026-08-07T00:00:00"
  };
};

const caseDetail = () => ({
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
  suggestions: fixtures.withSuggestion ? [suggestion()] : []
});

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
  getSupportCase: vi.fn().mockImplementation(() => Promise.resolve(caseDetail())),
  assignSupportCase: vi.fn(),
  transitionSupportCase: vi.fn(),
  sendManualReply: vi.fn(),
  generateSupportSuggestion: vi.fn().mockImplementation(
    () => new Promise((resolve) => fixtures.generateResolvers.push(resolve))
  ),
  decideSupportSuggestion: vi.fn().mockResolvedValue({}),
  raiseSupportEscalation: vi.fn()
}));

afterEach(() => {
  cleanup();
  fixtures.risk = "low";
  fixtures.withSuggestion = true;
  fixtures.citationGroups = null;
  fixtures.generateResolvers.length = 0;
  vi.clearAllMocks();
});

describe("SupportWorkbenchCopilot", () => {
  it("shows the short generating status and only disables the generate button while AI runs", async () => {
    render(<SupportWorkbenchPage />);

    const generate = await screen.findByRole("button", { name: "生成" });
    fireEvent.click(generate);

    expect(await screen.findByText("AI 正在处理")).toBeInTheDocument();
    expect(screen.getByText("核对订单信息")).toBeInTheDocument();
    expect(screen.getByText("查询适用规则")).toBeInTheDocument();
    expect(screen.getByText("正在评估处理风险")).toBeInTheDocument();
    expect(generate).toBeDisabled();
    expect(screen.getByRole("button", { name: "采纳并发送" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /解决/ })).toBeEnabled();

    fixtures.generateResolvers[0]?.(null);

    await waitFor(() =>
      expect(screen.queryByText("AI 正在处理")).not.toBeInTheDocument()
    );
    expect(await screen.findByRole("textbox", { name: "可编辑的对客回复" })).toBeInTheDocument();
  });

  it("hides the model / prompt / latency tech line from the reviewer actions", async () => {
    render(<SupportWorkbenchPage />);

    await screen.findByRole("textbox", { name: "可编辑的对客回复" });

    expect(screen.queryByText(/deepseek-flash/)).not.toBeInTheDocument();
    expect(screen.queryByText(/support-v1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/620ms/)).not.toBeInTheDocument();
  });

  it("keeps the accept button disabled for medium risk until facts are confirmed", async () => {
    fixtures.risk = "medium";
    render(<SupportWorkbenchPage />);

    const accept = await screen.findByRole("button", { name: "采纳并发送" });
    expect(accept).toBeDisabled();

    const confirm = screen.getByRole("checkbox", { name: "我已核对事实与规则" });
    expect(confirm).not.toBeChecked();

    fireEvent.click(confirm);
    expect(confirm).toBeChecked();
    expect(accept).toBeEnabled();

    fireEvent.click(accept);

    await waitFor(() =>
      expect(decideSupportSuggestion).toHaveBeenCalledWith(
        3,
        7,
        "accepted",
        "已为您确认退款政策，预计 3-5 个工作日到账。",
        undefined,
        true
      )
    );
  });

  it("blocks the accept button and highlights escalation for high risk", async () => {
    fixtures.risk = "high";
    render(<SupportWorkbenchPage />);

    const accept = await screen.findByRole("button", { name: "采纳并发送" });
    expect(accept).toBeDisabled();
    expect(screen.getByText("高风险建议必须升级主管处理")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "我已核对事实与规则" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "升级主管" })).toBeEnabled();
  });

  it("renders the resolution summary blocks for facts, pending items, rules and risk", async () => {
    fixtures.citationGroups = {
      orderFacts: [{ type: "order", content: "订单已支付 128.00 元" }],
      rules: [{ content: "生鲜类退款需 48 小时内确认" }]
    };
    render(<SupportWorkbenchPage />);

    const summary = await screen.findByRole("region", { name: "AI 处理建议" });

    expect(summary.getAttribute("aria-label")).toBe("AI 处理建议");
    expect(await screen.findByText("已核实事实")).toBeInTheDocument();
    expect(screen.getByText("订单已支付 128.00 元")).toBeInTheDocument();
    expect(screen.getByText("待确认")).toBeInTheDocument();
    expect(screen.getByText("退款到账时间待确认")).toBeInTheDocument();
    expect(screen.getByText("适用规则")).toBeInTheDocument();
    expect(screen.getByText("规则依据 1")).toBeInTheDocument();
    expect(screen.getByText("建议动作")).toBeInTheDocument();
    expect(screen.getByText("1.")).toBeInTheDocument();
    expect(screen.getByText("按退款规则核对后回复")).toBeInTheDocument();
    expect(screen.getByText("低")).toBeInTheDocument();
  });

  it("groups the evidence panel by order facts and rules when citationGroups is present", async () => {
    fixtures.citationGroups = {
      orderFacts: [
        { type: "order", content: "支付流水已进入人工复核队列" },
        { type: "order", content: "收货地址为杭州市西湖区" }
      ],
      rules: [{ content: "生鲜类退款需 48 小时内确认" }]
    };
    render(<SupportWorkbenchPage />);

    const toggle = await screen.findByRole("button", { name: "处理依据" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("支付流水已进入人工复核队列")).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("订单事实")).toBeInTheDocument();
    expect(screen.getByText("规则依据")).toBeInTheDocument();
    expect(screen.getByText("支付流水已进入人工复核队列")).toBeInTheDocument();
    expect(screen.getByText("收货地址为杭州市西湖区")).toBeInTheDocument();
    expect(screen.getByText("生鲜类退款需 48 小时内确认")).toBeInTheDocument();
  });
});
