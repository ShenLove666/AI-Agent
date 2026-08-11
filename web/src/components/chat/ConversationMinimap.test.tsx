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
  it("每轮一根线；当前轮（activeIndex）aria-current 高亮", () => {
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={2} onNavigate={() => {}} />);
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 5 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 3 轮对话" }).getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" }).getAttribute("aria-current")).not.toBe("true");
  });

  it("点击 → onNavigate 携带真实 turn 索引", () => {
    const onNavigate = vi.fn();
    render(<ConversationMinimap turns={makeTurns(5)} activeIndex={0} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 4 轮对话" }));
    expect(onNavigate).toHaveBeenCalledWith(3);
  });

  it("超过 40 轮 → 采样到 40 个槽位；首尾槽位对应真实首尾轮，点击反算真实索引", () => {
    const onNavigate = vi.fn();
    render(<ConversationMinimap turns={makeTurns(80)} activeIndex={0} onNavigate={onNavigate} />);

    // 40 个槽位（第 1 轮 + 第 80 轮 + 中间采样）
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 80 轮对话" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(40);

    // 采样槽位：约中间槽 → 真实索引（39/39 * 79 ≈ 79 → 第 80 轮附近）
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 80 轮对话" }));
    expect(onNavigate).toHaveBeenCalledWith(79);
  });

  it("采样后 activeIndex 映射到对应槽位（最后一条始终对应最后槽位）", () => {
    // 80 轮，activeIndex=79（最后一条）→ 最后一个槽位高亮
    render(<ConversationMinimap turns={makeTurns(80)} activeIndex={79} onNavigate={() => {}} />);
    expect(screen.getByRole("button", { name: "跳转到第 80 轮对话" }).getAttribute("aria-current")).toBe("true");
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

  it("ratios 提供真实高度比例 → 圆点按比例定位（长回答占更长轨道）", () => {
    // 3 轮：高度 100 / 300 / 100 → 中心比例 0.1 / 0.5 / 0.9
    render(
      <ConversationMinimap
        turns={makeTurns(3)}
        activeIndex={1}
        ratios={[0.1, 0.5, 0.9]}
        onNavigate={() => {}}
      />
    );
    const getTop = (label: string) =>
      screen.getByRole("button", { name: label }).style.top;
    expect(getTop("跳转到第 1 轮对话")).toBe("10%");
    expect(getTop("跳转到第 2 轮对话")).toBe("50%");
    expect(getTop("跳转到第 3 轮对话")).toBe("90%");
  });

  it("ratios 为 null 时回退均匀分布", () => {
    render(<ConversationMinimap turns={makeTurns(3)} activeIndex={0} onNavigate={() => {}} />);
    const getTop = (label: string) =>
      screen.getByRole("button", { name: label }).style.top;
    expect(getTop("跳转到第 1 轮对话")).toBe("0%");
    expect(getTop("跳转到第 2 轮对话")).toBe("50%");
    expect(getTop("跳转到第 3 轮对话")).toBe("100%");
  });
});
