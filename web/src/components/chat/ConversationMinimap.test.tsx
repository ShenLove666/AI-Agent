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

describe("ConversationMinimap", () => {
  it("每轮一根横线；当前轮（activeIndex）aria-current 高亮", () => {
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={2} onNavigate={() => {}} />);
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 5 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 3 轮对话" }).getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" }).getAttribute("aria-current")).not.toBe("true");
  });

  it("activeIndex 为 null 时不显示任何高亮（布局未完成/会话切换）", () => {
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={null} onNavigate={() => {}} />);
    expect(screen.getAllByRole("button").every((b) => b.getAttribute("aria-current") === null)).toBe(true);
  });

  it("点击 → onNavigate 携带真实 turn 索引", () => {
    const onNavigate = vi.fn();
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={0} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 4 轮对话" }));
    expect(onNavigate).toHaveBeenCalledWith(3);
  });

  it("超过 36 轮 → 均匀采样到 36 根线；首尾槽位对应真实首尾轮，点击反算真实索引", () => {
    const onNavigate = vi.fn();
    render(<ConversationMinimap turns={makeTurns(80)} activeIndex={0} onNavigate={onNavigate} />);

    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 80 轮对话" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(36);

    fireEvent.click(screen.getByRole("button", { name: "跳转到第 80 轮对话" }));
    expect(onNavigate).toHaveBeenCalledWith(79);
  });

  it("采样后 activeIndex 映射到最近槽位（最后一条 → 最后一个槽位高亮）", () => {
    render(<ConversationMinimap turns={makeTurns(80)} activeIndex={79} onNavigate={() => {}} />);
    expect(screen.getByRole("button", { name: "跳转到第 80 轮对话" }).getAttribute("aria-current")).toBe("true");
  });

  it("36 轮以内全部渲染，不采样", () => {
    render(<ConversationMinimap turns={makeTurns(36)} activeIndex={0} onNavigate={() => {}} />);
    expect(screen.getAllByRole("button")).toHaveLength(36);
    expect(screen.getByRole("button", { name: "跳转到第 36 轮对话" })).toBeInTheDocument();
  });

  it("hover 显示 tooltip：第 N 轮 + 摘要（超过 30 字截断）", () => {
    render(
      <ConversationMinimap
        turns={makeTurns(2, (i) => `这是一段特别长的用户问题描述需要被摘要展示${"很长".repeat(20)}`)}
        activeIndex={0}
        onNavigate={() => {}}
      />
    );
    fireEvent.mouseEnter(screen.getByRole("button", { name: "跳转到第 1 轮对话" }));
    // 每根线都带一个 tooltip（显示/隐藏由 CSS group-hover 控制，jsdom 不应用样式）；
    // 断言第 1 根线的 tooltip 内容正确
    const tooltip = screen.getAllByRole("tooltip")[0]!;
    expect(tooltip).toBeInTheDocument();
    expect(tooltip.textContent).toContain("第 1 轮");
    // 摘要截断到 30 字并追加省略号（不含「第 N 轮」标签）
    const summary = tooltip.textContent!.replace("第 1 轮", "").trim();
    expect(summary.length).toBeLessThanOrEqual(31);
    expect(summary.endsWith("…")).toBe(true);
  });
});
