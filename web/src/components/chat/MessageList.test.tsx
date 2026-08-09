import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MessageList } from "@/components/chat/MessageList";
import { useChatStore } from "@/stores/chatStore";
import type { Message } from "@/types";

function makeMessage(id: string, role: "user" | "assistant", content: string): Message {
  return {
    id,
    role,
    content,
    status: role === "user" ? "sent" : "done",
    createdAt: "2026-08-09T12:00:00Z",
    updatedAt: "2026-08-09T12:00:00Z"
  } as Message;
}

function renderList(messages: Message[], isStreaming = false) {
  useChatStore.setState({ recommendReveal: null });
  return render(
    <MessageList messages={messages} isLoading={false} isStreaming={isStreaming} />
  );
}

function findScroller(): HTMLElement | null {
  return document.querySelector('[data-testid="virtuoso-scroller"]');
}

function fireScroll(top: number, total: number, client: number) {
  const scroller = findScroller();
  if (!scroller) throw new Error("scroller not found");
  Object.defineProperty(scroller, "scrollTop", { value: top, configurable: true });
  Object.defineProperty(scroller, "scrollHeight", { value: total, configurable: true });
  Object.defineProperty(scroller, "clientHeight", { value: client, configurable: true });
  act(() => {
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
}

afterEach(cleanup);

describe("MessageList scroll-follow behavior", () => {
  it("shows the scroll-to-bottom button once the user scrolls away from the bottom", () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    renderList(messages, true);

    // 用户在底部时按钮不出现（距底 0 < 160）
    fireScroll(200, 500, 300);
    expect(screen.queryByRole("button", { name: "滚动到底部" })).not.toBeInTheDocument();

    // 用户滚离底部（距底 200 > 160 阈值）→ 按钮出现
    fireScroll(0, 500, 300);
    expect(screen.getByRole("button", { name: "滚动到底部" })).toBeInTheDocument();

    // 回到底部 → 按钮消失
    fireScroll(200, 500, 300);
    expect(screen.queryByRole("button", { name: "滚动到底部" })).not.toBeInTheDocument();
  });
});
