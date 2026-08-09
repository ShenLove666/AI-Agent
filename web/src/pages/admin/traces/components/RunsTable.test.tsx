import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunsTable } from "@/pages/admin/traces/components/RunsTable";
import type { RagTraceRun } from "@/services/ragTraceService";

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
    renderTable();

    expect(screen.getByText(TRACE_ID)).toHaveAttribute("title", TRACE_ID);
    const copyButton = screen.getByRole("button", {
      name: `复制 Trace Id ${TRACE_ID}`
    });
    expect(copyButton).toHaveClass("opacity-100");

    await user.click(copyButton);
    expect(writeText).toHaveBeenCalledWith(TRACE_ID);
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
