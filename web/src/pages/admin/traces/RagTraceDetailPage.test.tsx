import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RagTraceDetailPage } from "@/pages/admin/traces/RagTraceDetailPage";
import { getRagTraceDetail } from "@/services/ragTraceService";

vi.mock("@/services/ragTraceService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ragTraceService")>();
  return {
    ...actual,
    getRagTraceDetail: vi.fn()
  };
});

const TRACE_ID = "a76069184bc9433381399e6a75c6f86b";

function makeDetail(status: string) {
  return {
    run: {
      traceId: TRACE_ID,
      traceName: "RAG Chat",
      status,
      durationMs: 4220,
      question: "1+3=?",
      startTime: "2026-08-11T12:00:00Z"
    },
    nodes: []
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/admin/traces/${TRACE_ID}`]}>
      <Routes>
        <Route path="/admin/traces/:traceId" element={<RagTraceDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("RagTraceDetailPage RUNNING 轮询", () => {
  it("running → running → running → success：持续轮询直到终态，随后停止", async () => {
    const mockGet = vi.mocked(getRagTraceDetail);
    // 首次加载 + 三次轮询都返回 running，第四次轮询返回 success
    mockGet
      .mockResolvedValueOnce(makeDetail("running"))
      .mockResolvedValueOnce(makeDetail("running"))
      .mockResolvedValueOnce(makeDetail("running"))
      .mockResolvedValueOnce(makeDetail("running"))
      .mockResolvedValueOnce(makeDetail("success"));

    renderPage();
    // 首次加载（非 silent）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);

    // 第一次轮询（800ms）：仍 running → 继续
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);

    // 第二次轮询：仍 running → 继续
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(3);

    // 第三次轮询：仍 running → 继续
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(4);

    // 第四次轮询：success → 停止
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(5);

    // 终态后不再安排下一次：再等 2 秒无新请求
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(mockGet).toHaveBeenCalledTimes(5);

    // UI 显示 SUCCESS（fake timers 下同步断言，不用 findBy）
    expect(screen.getByText("SUCCESS")).toBeInTheDocument();
  });

  it("running → failed：进入终态后停止轮询", async () => {
    const mockGet = vi.mocked(getRagTraceDetail);
    mockGet
      .mockResolvedValueOnce(makeDetail("running"))
      .mockResolvedValueOnce(makeDetail("failed"));

    renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(800);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("unmount 后 pending timer 被清除：不再发起新请求", async () => {
    const mockGet = vi.mocked(getRagTraceDetail);
    mockGet.mockResolvedValue(makeDetail("running"));

    const { unmount } = renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});
