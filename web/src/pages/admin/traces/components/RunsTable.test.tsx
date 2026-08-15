import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunsTable } from "@/pages/admin/traces/components/RunsTable";
import type { RagTraceRun } from "@/services/ragTraceService";

vi.mock("@/services/ragTraceService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ragTraceService")>();
  return {
    ...actual,
    getRagTraceNodes: vi.fn().mockResolvedValue([])
  };
});

const TRACE_ID = "783e431ce4cd4409806d3ebecc6d9b87";
const nativeClipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const globalsCss = readFileSync(resolve(process.cwd(), "src/styles/globals.css"), "utf8");

const run: RagTraceRun = {
  traceId: TRACE_ID,
  question: "牛奶配送超时了，怎么办？",
  userName: "merchant-demo",
  durationMs: 13_660,
  ttftMs: 420,
  status: "success",
  startTime: "2026-08-09T10:00:00Z"
};

const renderTable = () =>
  render(
    <RunsTable
      runs={[run]}
      loading={false}
      current={1}
      pages={3}
      total={21}
      onOpenRun={vi.fn()}
      onPrevPage={vi.fn()}
      onNextPage={vi.fn()}
    />
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  if (nativeClipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", nativeClipboardDescriptor);
  } else {
    Reflect.deleteProperty(navigator, "clipboard");
  }
  Reflect.deleteProperty(window, "isSecureContext");
});

describe("RunsTable", () => {
  it("keeps every column reachable through a labelled two-axis scroll region", () => {
    renderTable();

    const scrollRegion = screen.getByRole("region", { name: "链路运行列表" });
    expect(scrollRegion).toHaveClass("overflow-x-auto", "overflow-y-auto");
    expect(screen.getByRole("table")).toHaveClass("min-w-[1360px]");

    expect(screen.getByText("第 1 / 3 页，共 21 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeEnabled();
  });

  it("exposes the complete Trace Id and keeps its copy action visible", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText }
    });
    // copyText 在 secure context 下才走 Clipboard API（否则降级 execCommand）
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: true
    });
    renderTable();

    expect(screen.getByText(TRACE_ID)).toHaveAttribute("title", TRACE_ID);
    const copyButton = screen.getByRole("button", {
      name: `复制 Trace Id ${TRACE_ID}`
    });
    expect(copyButton).toHaveClass("opacity-100");

    await user.click(copyButton);
    expect(writeText).toHaveBeenCalledWith(TRACE_ID);
  });

  it("概览弹窗跟随最新 runs：同 traceId 从 RUNNING 变 SUCCESS，无需重新打开", async () => {
    const user = userEvent.setup();
    const runningRun: RagTraceRun = {
      ...run,
      status: "running",
      durationMs: null,
      ttftMs: null
    };
    const { rerender } = render(
      <RunsTable
        runs={[runningRun]}
        loading={false}
        current={1}
        pages={1}
        total={1}
        onOpenRun={vi.fn()}
        onPrevPage={vi.fn()}
        onNextPage={vi.fn()}
      />
    );

    // 打开 RUNNING 那条的「链路概览」（列表行与弹窗各一个 RUNNING 徽标）
    const briefButton = screen.getByRole("button", { name: /概览/ });
    await user.click(briefButton);
    expect(screen.getByText("链路概览")).toBeInTheDocument();
    expect(screen.getAllByText("RUNNING").length).toBeGreaterThanOrEqual(2);

    // 父级 runs 更新为同 traceId SUCCESS（列表轮询的结果）→ 弹窗自动跟随
    const successRun: RagTraceRun = { ...run, status: "success" };
    rerender(
      <RunsTable
        runs={[successRun]}
        loading={false}
        current={1}
        pages={1}
        total={1}
        onOpenRun={vi.fn()}
        onPrevPage={vi.fn()}
        onNextPage={vi.fn()}
      />
    );

    expect(screen.getAllByText("SUCCESS").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryAllByText("RUNNING")).toHaveLength(0);
    // 弹窗仍打开（未重新打开）
    expect(screen.getByText("链路概览")).toBeInTheDocument();
  });

  it("keeps a high-contrast scrollbar visible while the list is idle", () => {
    renderTable();

    expect(screen.getByRole("region", { name: "链路运行列表" })).toHaveClass(
      "trace-list-persistent-scrollbar"
    );
    expect(globalsCss).toMatch(
      /\.admin-layout \.trace-list-persistent-scrollbar\s*\{[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-color:\s*#475569\s+#e2e8f0;[^}]*scrollbar-gutter:\s*stable;/s
    );
    expect(globalsCss).toMatch(
      /\.admin-layout \.trace-list-persistent-scrollbar::-webkit-scrollbar\s*\{[^}]*width:\s*10px;[^}]*height:\s*10px;/s
    );
    expect(globalsCss).toMatch(
      /\.admin-layout \.trace-list-persistent-scrollbar::-webkit-scrollbar-thumb\s*\{[^}]*background:\s*#475569;/s
    );
    expect(globalsCss).toMatch(
      /\.admin-layout \.trace-list-persistent-scrollbar::-webkit-scrollbar-track\s*\{[^}]*background:\s*#e2e8f0;/s
    );
  });
});
