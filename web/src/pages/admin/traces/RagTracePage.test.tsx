import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RagTracePage } from "@/pages/admin/traces/RagTracePage";
import { getRagTraceRuns } from "@/services/ragTraceService";

vi.mock("@/services/ragTraceService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ragTraceService")>();
  return {
    ...actual,
    getRagTraceRuns: vi.fn()
  };
});

const TRACE_ID = "a76069184bc9433381399e6a75c6f86b";

function pageResult(status: string) {
  return {
    records: [
      {
        traceId: TRACE_ID,
        question: "1+3=?",
        userName: "admin",
        durationMs: status === "success" ? 4220 : null,
        ttftMs: status === "success" ? 670 : null,
        status,
        startTime: "2026-08-11T12:00:00Z"
      }
    ],
    total: 1,
    size: 10,
    current: 1,
    pages: 1
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("RagTracePage 自适应轮询", () => {
  it("列表存在 RUNNING → 800ms 轮询，终态后仍 5s idle 低频刷新；poll 期间不闪加载中", async () => {
    const mockGet = vi.mocked(getRagTraceRuns);
    // 首载 running → poll running → poll success
    mockGet
      .mockResolvedValueOnce(pageResult("running"))
      .mockResolvedValueOnce(pageResult("running"))
      .mockResolvedValueOnce(pageResult("success"));

    render(
      <MemoryRouter>
        <RagTracePage />
      </MemoryRouter>
    );

    // 首次加载（非 silent）：显示 RUNNING
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(screen.getByText("RUNNING")).toBeInTheDocument();

    // poll 1（800ms）：仍 running → 继续
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);

    // poll 2（800ms）：success → 表格变 SUCCESS（silent，不闪「加载中...」）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(3);
    expect(screen.getByText("SUCCESS")).toBeInTheDocument();
    expect(screen.queryByText("加载中...")).not.toBeInTheDocument();

    // 终态后进入 5s idle 低频刷新：仍会继续请求（另一标签页的新 Trace 能出现）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockGet).toHaveBeenCalledTimes(4);
  });

  it("unmount 后清除 pending timer：不再发起新请求", async () => {
    const mockGet = vi.mocked(getRagTraceRuns);
    mockGet.mockResolvedValue(pageResult("running"));

    const { unmount } = render(
      <MemoryRouter>
        <RagTracePage />
      </MemoryRouter>
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});
