import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RetailOperationsPage } from "./RetailOperationsPage";

const overview = {
  ready: true,
  dataState: "ready",
  profile: {
    name: "邻里鲜选",
    businessType: "即时零售",
    storeCount: 0,
    goal: "提升连带",
    stage: "demo"
  },
  summary: {
    orders: 100,
    rows: 300,
    products: 20,
    averageBasketSize: 3,
    rules: 1,
    sources: 1,
    sourceFingerprint: "abc",
    origin: "observed+derived"
  },
  rules: [
    {
      id: 1,
      from: "牛奶",
      to: "面包",
      count: 20,
      support: 0.2,
      confidence: 0.4,
      lift: 1.8,
      evidence: ["订单 97"],
      origin: "derived"
    }
  ],
  campaigns: [
    {
      id: 11,
      name: "购物篮搭配购运营方案",
      status: "draft",
      version: 1,
      rule: {
        from: "牛奶",
        to: "面包",
        count: 20,
        support: 20,
        confidence: 40,
        lift: 1.8,
        evidence: ["订单 97"]
      }
    }
  ],
  metrics: [
    {
      key: "acceptance",
      label: "建议采用率",
      value: 80,
      numerator: 8,
      denominator: 10,
      unit: "%",
      dataState: "demo",
      origin: "synthetic"
    }
  ],
  tasks: [],
  evaluations: []
};

const dataSources = [
  {
    id: 1,
    datasetKey: "uci",
    version: "v1",
    title: "真实零售快照",
    sourceKind: "public",
    sourceUri: "https://example.com",
    publisher: "UCI",
    license: "CC BY",
    retrievedAt: "2026-08-01",
    encoding: "utf-8",
    transformVersion: "v2",
    manifestSha256: "a".repeat(64),
    limitations: [],
    counts: { orders: 100 },
    acceptedRows: 300,
    rejectedRows: 0,
    isDemo: true
  }
];

const campaignDetail = {
  id: 11,
  name: "购物篮搭配购运营方案",
  status: "draft",
  version: 1,
  lockVersion: 1,
  rejectedReason: null,
  publishedAt: null,
  createdAt: "2026-08-09T10:00:00",
  updatedAt: "2026-08-09T10:00:00",
  rule: {
    id: 1,
    count: 20,
    support: 20,
    confidence: 40,
    lift: 1.8,
    evidence: ["订单 97"],
    origin: "derived"
  },
  versions: [
    {
      version: 1,
      channel: "淘宝闪购",
      copy: "基于购物篮证据创建的搭配购方案。",
      ruleSnapshot: {},
      approvedBy: null,
      approvedAt: null,
      createdAt: "2026-08-09T10:00:00"
    }
  ],
  task: null
};

const mocks = vi.hoisted(() => ({
  getRetailOverview: vi.fn(),
  getRetailDataSources: vi.fn(),
  getRetailDataSourceQuality: vi.fn(),
  getRetailDataSourcePreview: vi.fn(),
  createRetailCampaign: vi.fn(),
  transitionRetailCampaign: vi.fn(),
  transitionRetailTask: vi.fn(),
  getRetailCampaign: vi.fn(),
  getRetailTask: vi.fn(),
  assignRetailTask: vi.fn(),
  verifyRetailTask: vi.fn(),
  syncFailedEvaluations: vi.fn(),
  getRetailReport: vi.fn()
}));

vi.mock("@/services/retailService", () => mocks);

const authState = vi.hoisted(() => ({ permissions: ["retail.view"] }));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (state: { user: { permissions: string[] } }) => unknown) =>
    selector({ user: { permissions: authState.permissions } })
}));

function mockPermissions(permissions: string[]) {
  authState.permissions = permissions;
}

describe("RetailOperations", () => {
  afterEach(() => {
    cleanup();
  });
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.getRetailOverview.mockResolvedValue(overview);
    mocks.getRetailDataSources.mockResolvedValue(dataSources);
    mocks.getRetailCampaign.mockResolvedValue(campaignDetail);
    mocks.getRetailReport.mockResolvedValue({ filename: "report.md", content: "# 周报" });
  });

  it("labels observed, derived and synthetic populations", async () => {
    mockPermissions(["retail.view"]);
    render(<RetailOperationsPage />);
    expect(await screen.findByText("真实零售快照")).toBeInTheDocument();
    expect(screen.getAllByText("真实观测数据").length).toBeGreaterThan(0);
    expect(screen.getAllByText("可复算衍生指标").length).toBeGreaterThan(0);
    expect(screen.getAllByText("模拟运营数据").length).toBeGreaterThan(0);
    expect(screen.getByText("转换 v2")).toBeInTheDocument();
  });

  it("opens campaign detail drawer and confirms with expectedVersion", async () => {
    mockPermissions(["campaign.confirm", "campaign.publish", "retail.view"]);
    const user = userEvent.setup();
    render(<RetailOperationsPage />);

    const card = await screen.findByText("购物篮搭配购运营方案");
    await user.click(card);

    expect(await screen.findByText("方案文案 · v1 · 淘宝闪购")).toBeInTheDocument();
    expect(screen.getByText(/基于购物篮证据创建的搭配购方案/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /确认方案/ }));
    await waitFor(() => {
      expect(mocks.transitionRetailCampaign).toHaveBeenCalledWith(11, "confirm", 1, undefined);
    });
  });

  it("hides confirm action without campaign.confirm permission", async () => {
    mockPermissions(["retail.view"]);
    const user = userEvent.setup();
    render(<RetailOperationsPage />);

    const card = await screen.findByText("购物篮搭配购运营方案");
    await user.click(card);
    await screen.findByText("方案文案 · v1 · 淘宝闪购");
    expect(screen.queryByRole("button", { name: /确认方案/ })).not.toBeInTheDocument();
  });

  it("rejects with a required reason", async () => {
    mockPermissions(["campaign.confirm", "retail.view"]);
    const user = userEvent.setup();
    render(<RetailOperationsPage />);

    const card = await screen.findByText("购物篮搭配购运营方案");
    await user.click(card);
    await screen.findByText("方案文案 · v1 · 淘宝闪购");

    await user.click(screen.getByRole("button", { name: /驳回方案/ }));
    // 空原因不触发驳回请求（提示以 toast 呈现，测试环境不渲染）
    expect(mocks.transitionRetailCampaign).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/驳回原因/), "毛利不足");
    await user.click(screen.getByRole("button", { name: /驳回方案/ }));
    await waitFor(() => {
      expect(mocks.transitionRetailCampaign).toHaveBeenCalledWith(11, "reject", 1, "毛利不足");
    });
  });

  it("shows task empty state and sync action for task.assign holders", async () => {
    mockPermissions(["task.assign", "retail.view"]);
    mocks.syncFailedEvaluations.mockResolvedValue({ created: 2 });
    const user = userEvent.setup();
    render(<RetailOperationsPage />);

    expect(await screen.findByText(/暂无优化任务/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /从失败评测创建任务/ }));
    await waitFor(() => {
      expect(mocks.syncFailedEvaluations).toHaveBeenCalled();
    });
  });

  it("hides create-campaign action without permission", async () => {
    mockPermissions(["retail.view"]);
    render(<RetailOperationsPage />);
    await screen.findByText("真实零售快照");
    expect(screen.queryByRole("button", { name: /创建方案/ })).not.toBeInTheDocument();
  });
});
