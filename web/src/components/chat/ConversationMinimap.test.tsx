import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationMinimap } from "@/components/chat/ConversationMinimap";
import type { ChatTurn } from "@/utils/chatTurns";

afterEach(() => {
  cleanup();
});

function makeTurns(count: number, content: (i: number) => string = (i) => `问题${i + 1}`): ChatTurn[] {
  return Array.from({ length: count }, (_, i) => ({
    key: `turn-${i + 1}`,
    turnId: i + 1,
    user: {
      id: `u${i + 1}`,
      role: "user",
      content: content(i),
      status: "sent",
      createdAt: "2026-08-09T12:00:00Z",
      updatedAt: "2026-08-09T12:00:00Z"
    } as ChatTurn["user"]
  }));
}

function marker(label: string): HTMLButtonElement {
  return screen.getByRole("button", { name: label }) as HTMLButtonElement;
}

function markerWidth(label: string): string {
  return marker(label).querySelector("span")?.getAttribute("style") ?? "";
}

describe("ConversationMinimap fisheye rail", () => {
  it("默认状态：所有线等长 8px，active 靠颜色/粗细区分（Codex 式，不靠长度）", () => {
    render(<ConversationMinimap turns={makeTurns(6)} activeIndex={5} onNavigate={() => {}} />);
    expect(marker("跳转到第 6 轮对话").getAttribute("aria-current")).toBe("true");
    // active 与普通线等长
    expect(markerWidth("跳转到第 6 轮对话")).toContain("width: 16px");
    expect(markerWidth("跳转到第 1 轮对话")).toContain("width: 16px");
    expect(markerWidth("跳转到第 6 轮对话")).toBe(markerWidth("跳转到第 1 轮对话"));
  });

  it("activeIndex 为 null 时不显示任何高亮", () => {
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={null} onNavigate={() => {}} />);
    expect(screen.getAllByRole("button").every((b) => b.getAttribute("aria-current") === null)).toBe(true);
  });

  it("fisheye：hover 中心 30px，±1 24px，±2 18px，±3 13px，更远回落到 8px", () => {
    render(<ConversationMinimap turns={makeTurns(20)} activeIndex={null} onNavigate={() => {}} />);
    fireEvent.mouseEnter(marker("跳转到第 9 轮对话")); // index 8

    expect(markerWidth("跳转到第 9 轮对话")).toContain("width: 36px"); // hover
    expect(markerWidth("跳转到第 8 轮对话")).toContain("width: 28px"); // -1
    expect(markerWidth("跳转到第 10 轮对话")).toContain("width: 28px"); // +1
    expect(markerWidth("跳转到第 7 轮对话")).toContain("width: 20px"); // -2
    expect(markerWidth("跳转到第 11 轮对话")).toContain("width: 20px"); // +2
    expect(markerWidth("跳转到第 6 轮对话")).toContain("width: 14px"); // -3
    expect(markerWidth("跳转到第 12 轮对话")).toContain("width: 14px"); // +3
    expect(markerWidth("跳转到第 5 轮对话")).toContain("width: 16px"); // -4 → 回落
    expect(markerWidth("跳转到第 13 轮对话")).toContain("width: 16px"); // +4 → 回落
  });

  it("active 与 hover 分开控制：active 远离 hover 时回落 8px，颜色保持深色高亮", () => {
    render(<ConversationMinimap turns={makeTurns(12)} activeIndex={2} onNavigate={() => {}} />);
    fireEvent.mouseEnter(marker("跳转到第 9 轮对话")); // hover index 8，远离 active 2

    // active marker（第 3 轮）保持高亮（颜色/粗细），但长度回落 8px
    expect(marker("跳转到第 3 轮对话").getAttribute("aria-current")).toBe("true");
    expect(markerWidth("跳转到第 3 轮对话")).toContain("width: 16px");
    // hover marker 最大
    expect(markerWidth("跳转到第 9 轮对话")).toContain("width: 36px");
  });

  it("长对话全量渲染：100 轮 → 100 个 marker，不再采样", () => {
    render(<ConversationMinimap turns={makeTurns(100)} activeIndex={0} onNavigate={() => {}} />);
    expect(screen.getAllByRole("button")).toHaveLength(100);
    expect(marker("跳转到第 1 轮对话")).toBeInTheDocument();
    expect(marker("跳转到第 100 轮对话")).toBeInTheDocument();
  });

  it("rail 自身可滚动：overflow-y-auto + 隐藏 scrollbar + overscroll-contain", () => {
    render(<ConversationMinimap turns={makeTurns(100)} activeIndex={0} onNavigate={() => {}} />);
    const rail = marker("跳转到第 1 轮对话").parentElement!;
    expect(rail.className).toContain("overflow-y-auto");
    expect(rail.className).toContain("overscroll-contain");
    expect(rail.className).toContain("[scrollbar-width:none]");
    expect(rail.className).toContain("[&::-webkit-scrollbar]:hidden");
  });

  it("点击 → onNavigate 携带真实 turn 索引", () => {
    const onNavigate = vi.fn();
    render(<ConversationMinimap turns={makeTurns(25)} activeIndex={0} onNavigate={onNavigate} />);
    fireEvent.click(marker("跳转到第 20 轮对话"));
    expect(onNavigate).toHaveBeenCalledWith(19);
  });

  it("hover 显示 tooltip：只含问题摘要（不暴露轮次编号），超过 30 字截断", () => {
    render(
      <ConversationMinimap
        turns={makeTurns(4, (i) => `这是一段特别长的用户问题描述需要被摘要展示${"很长".repeat(20)}`)}
        activeIndex={0}
        onNavigate={() => {}}
      />
    );
    fireEvent.mouseEnter(marker("跳转到第 1 轮对话"));
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toBeInTheDocument();
    expect(tooltip.textContent).not.toContain("第 1 轮");
    const summary = tooltip.textContent!.trim();
    expect(summary.length).toBeLessThanOrEqual(31);
    expect(summary.endsWith("…")).toBe(true);
  });

  it("指针离开 rail → 清除 hover 与 tooltip", () => {
    render(<ConversationMinimap turns={makeTurns(6)} activeIndex={0} onNavigate={() => {}} />);
    fireEvent.mouseEnter(marker("跳转到第 3 轮对话"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(markerWidth("跳转到第 3 轮对话")).toContain("width: 36px");

    fireEvent.mouseLeave(marker("跳转到第 3 轮对话"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(markerWidth("跳转到第 3 轮对话")).toContain("width: 16px");
  });

  /** 让 rail 可滚并 mock 指定 marker 的 offsetTop（jsdom 无布局，全为 0） */
  function mockRailGeometry(rail: HTMLElement, markerIndex: number, offsetTop: number) {
    Object.defineProperty(rail, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(rail, "clientHeight", { configurable: true, value: 300 });
    const el = Array.from(rail.querySelectorAll("button"))[markerIndex]!;
    Object.defineProperty(el, "offsetTop", { configurable: true, value: offsetTop });
    Object.defineProperty(el, "offsetHeight", { configurable: true, value: 9 });
  }

  it("hover 不暂停 active 自动跟随：active 变化时 rail 滚到中部舒适区", () => {
    const { rerender } = render(
      <ConversationMinimap turns={makeTurns(60)} activeIndex={0} onNavigate={() => {}} />
    );
    const rail = marker("跳转到第 1 轮对话").parentElement!;
    mockRailGeometry(rail, 50, 800);

    // active 移到第 51 轮（offsetTop 800，超出 30%~70% 舒适区）→ rail 居中
    rerender(<ConversationMinimap turns={makeTurns(60)} activeIndex={50} onNavigate={() => {}} />);
    // desiredTop = 800 - 150 + 4.5 = 654.5 → clamp(654.5, 700) = 654.5 → 654
    expect(rail.scrollTop).toBe(654.5);

    // 鼠标 hover 一根 marker：不暂停跟随——active 再变化仍会滚
    fireEvent.mouseEnter(marker("跳转到第 2 轮对话"));
    mockRailGeometry(rail, 10, 200);
    rerender(<ConversationMinimap turns={makeTurns(60)} activeIndex={10} onNavigate={() => {}} />);
    // desiredTop = 200 - 150 + 4.5 = 54.5 → 54
    expect(rail.scrollTop).toBe(54.5);
  });

  it("rail 上 wheel 暂停自动跟随；pointer leave 恢复", () => {
    const { rerender } = render(
      <ConversationMinimap turns={makeTurns(60)} activeIndex={0} onNavigate={() => {}} />
    );
    const nav = screen.getByRole("navigation", { name: "对话导航" });
    const rail = marker("跳转到第 1 轮对话").parentElement!;
    mockRailGeometry(rail, 50, 800);

    // 用户真的在 rail 上滚 wheel → 暂停自动跟随
    fireEvent.wheel(nav);
    rerender(<ConversationMinimap turns={makeTurns(60)} activeIndex={50} onNavigate={() => {}} />);
    expect(rail.scrollTop).toBe(0); // 暂停：不跟随

    // pointer leave → 恢复跟随：active 已变，effect 重新执行并居中
    fireEvent.pointerLeave(nav);
    expect(rail.scrollTop).toBe(654.5);
  });
});
