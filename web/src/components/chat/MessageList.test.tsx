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

describe("MessageList streaming follow behavior", () => {
  it("pins to the bottom immediately when streaming starts", async () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    // 先以非流式渲染让会话加载贴底标记过期，避免布局 effect 干扰
    const { rerender } = render(
      <MessageList messages={messages} isLoading={false} isStreaming={false} />
    );
    await new Promise((resolve) => setTimeout(resolve, 1600));

    const scroller = findScroller()!;
    Object.defineProperty(scroller, "scrollHeight", { value: 800, configurable: true, writable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 300, configurable: true, writable: true });
    Object.defineProperty(scroller, "scrollTop", { value: 500, configurable: true, writable: true });

    // 流式开始 → 强制贴底一次（发送时的明确贴底时机，此后内容增长由 Virtuoso followOutput 接管）
    rerender(<MessageList messages={messages} isLoading={false} isStreaming={true} />);

    return Promise.resolve().then(() => {
      expect(scroller.scrollTop).toBe(800);
    });
  });

  it("pauses following while streaming once the user scrolls away", async () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    const { rerender } = render(
      <MessageList messages={messages} isLoading={false} isStreaming={false} />
    );
    await new Promise((resolve) => setTimeout(resolve, 1600));

    rerender(<MessageList messages={messages} isLoading={false} isStreaming={true} />);
    // 等发送时的强制贴底（120ms）完成
    await new Promise((resolve) => setTimeout(resolve, 250));
    const scroller = findScroller()!;
    Object.defineProperty(scroller, "scrollHeight", { value: 800, configurable: true, writable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 300, configurable: true, writable: true });
    Object.defineProperty(scroller, "scrollTop", { value: 100, configurable: true, writable: true });
    // 用户滚离底部（距底 400 > 160）
    fireScroll(100, 800, 300);

    await new Promise((resolve) => setTimeout(resolve, 500));
    // 流式中滚离后不跟随（无轮询/定时拉回机制），位置保持
    expect(scroller.scrollTop).toBe(100);
  });
});

describe("MessageList stream-end scroll behavior", () => {
  it("force-scrolls to the bottom when the stream ends if the user never scrolled away", () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    const { rerender } = render(
      <MessageList messages={messages} isLoading={false} isStreaming={true} />
    );
    const scroller = findScroller();
    expect(scroller).not.toBeNull();
    Object.defineProperty(scroller!, "scrollHeight", { value: 800, configurable: true, writable: true });
    Object.defineProperty(scroller!, "clientHeight", { value: 300, configurable: true, writable: true });
    // 用户在底部（距底 0）
    Object.defineProperty(scroller!, "scrollTop", { value: 500, configurable: true, writable: true });

    rerender(<MessageList messages={messages} isLoading={false} isStreaming={false} />);

    // 完成时用户未滚离 → 立即贴底（scrollTop 被设为 scrollHeight），单次调用即可
    return Promise.resolve().then(() => {
      expect(scroller!.scrollTop).toBe(800);
    });
  });

  it("does not yank the viewport when the user scrolled away during streaming", async () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    // 先以非流式渲染让会话加载贴底标记（1500ms）注册并过期，避免布局 effect 干扰
    const { rerender } = render(
      <MessageList messages={messages} isLoading={false} isStreaming={false} />
    );
    await new Promise((resolve) => setTimeout(resolve, 1600));

    rerender(<MessageList messages={messages} isLoading={false} isStreaming={true} />);
    const scroller = findScroller();
    Object.defineProperty(scroller!, "scrollHeight", { value: 800, configurable: true, writable: true });
    Object.defineProperty(scroller!, "clientHeight", { value: 300, configurable: true, writable: true });
    Object.defineProperty(scroller!, "scrollTop", { value: 100, configurable: true, writable: true });
    // 用户滚离底部（距底 800-100-300=400 > 160）
    fireScroll(100, 800, 300);
    rerender(<MessageList messages={messages} isLoading={false} isStreaming={false} />);

    // 用户滚离过 → 完成时不抢滚动，位置保持
    return Promise.resolve().then(() => {
      expect(scroller!.scrollTop).toBe(100);
    });
  });
});

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

describe("MessageList stable viewKey", () => {
  it("sessionKey 从 null 变为会话 id（新会话首答落库）时不重建 Virtuoso；已存在 id → 另一 id 才重建", () => {
    const messages = [
      makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("m2", "assistant", "根据购物篮证据，推荐根茎类蔬菜（提升度 3.04）。")
    ];
    useChatStore.setState({ recommendReveal: null });
    const { rerender } = render(
      <MessageList messages={messages} isLoading={false} isStreaming={false} />
    );
    const scrollerBefore = findScroller();
    expect(scrollerBefore).not.toBeNull();

    // null → uuid（新会话首答落库）：Virtuoso 不重建，scroller 仍是同一 DOM 节点
    rerender(
      <MessageList messages={messages} isLoading={false} isStreaming={false} sessionKey="uuid-1" />
    );
    expect(findScroller()).toBe(scrollerBefore);

    // 已存在会话 id → 另一个 id（用户切换历史会话）：Virtuoso 重建，scroller 被替换
    rerender(
      <MessageList messages={messages} isLoading={false} isStreaming={false} sessionKey="uuid-2" />
    );
    const scrollerAfter = findScroller();
    expect(scrollerAfter).not.toBeNull();
    expect(scrollerAfter).not.toBe(scrollerBefore);
  });
});
