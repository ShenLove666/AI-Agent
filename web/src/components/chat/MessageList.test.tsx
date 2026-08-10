import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/MessageList";
import { useChatStore } from "@/stores/chatStore";
import type { AgentExecutionStep, Message } from "@/types";

// jsdom 没有 Element.scrollTo / scrollBy。Virtuoso 的 scrollToIndex 落地依赖它们，
// 这里补最小实现，供 mockScrollMetrics 之外的路径（如回到底部按钮）使用。
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = function (this: Element, options?: ScrollToOptions) {
    const top = typeof options === "object" && options ? options.top ?? 0 : 0;
    (this as HTMLElement).scrollTop = top;
  };
}
if (typeof Element.prototype.scrollBy !== "function") {
  Element.prototype.scrollBy = function (this: Element, options?: ScrollToOptions) {
    const top = typeof options === "object" && options ? options.top ?? 0 : 0;
    (this as HTMLElement).scrollTop += top;
  };
}

// 注意：jsdom 无真实布局，真实 Virtuoso 不会渲染虚拟化条目（条目渲染由
// ChatTurnItem.test 直接覆盖）。本文件把 react-virtuoso 替换为可控 mock：
// 渲染全部条目（复用 itemContent，Latest Turn ResizeObserver 因此能拿到
// 真实 DOM 节点）、提供 data-testid="virtuoso-scroller"、可 spy 的
// VirtuosoHandle（scrollToIndex / autoscrollToBottom）以及 atBottomStateChange
// 回调（scroll 事件 + 50ms 节流，与真实行为一致）。滚动度量仍通过
// mockScrollMetrics 在 scroller 实例上注入。

// ---- 可手动触发的 ResizeObserver stub ----
// jsdom 无真实 ResizeObserver 回调：stub 记录 observe/disconnect 并暴露 trigger()
// 供测试手动触发 Latest Turn 高度变化。setup.ts 里的空实现被本文件替换。
class MockResizeObserver {
  static instances: MockResizeObserver[] = [];
  private callback: ResizeObserverCallback;
  els: Element[] = [];
  disconnectCount = 0;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    MockResizeObserver.instances.push(this);
  }
  observe(el: Element) {
    this.els.push(el);
  }
  unobserve(): void {}
  disconnect() {
    this.disconnectCount += 1;
    this.els = [];
  }
  /** 手动触发一次高度变化回调 */
  trigger() {
    this.callback([], this as unknown as ResizeObserver);
  }
}
globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

// ---- react-virtuoso mock -------------------------------------------------
const virtuosoMock = vi.hoisted(() => {
  class VirtuosoHandleStub {
    scroller: HTMLElement | null = null;
    /** 与真实 Virtuoso 一致：jsdom 中 offsetHeight 为 0 时 scrollToIndex 直接返回 */
    scrollToIndex(opts: { index: number; align?: string; behavior?: ScrollBehavior }) {
      const el = this.scroller;
      if (!el || el.offsetHeight === 0) return;
      el.scrollTo({ top: el.scrollHeight, behavior: opts.behavior });
    }
    autoscrollToBottom() {
      const el = this.scroller;
      if (!el || el.offsetHeight === 0) return;
      el.scrollTo({ top: el.scrollHeight });
    }
  }
  const instances: InstanceType<typeof VirtuosoHandleStub>[] = [];
  return { VirtuosoHandleStub, instances };
});

vi.mock("react-virtuoso", async () => {
  const React = await import("react");
  const { VirtuosoHandleStub, instances } = virtuosoMock;

  interface VirtuosoMockProps {
    data?: unknown[];
    itemContent?: (index: number, item: unknown) => React.ReactNode;
    components?: { List?: unknown; Footer?: unknown };
    scrollerRef?: (el: HTMLElement | null) => void;
    followOutput?: (isAtBottom: boolean) => false | "auto";
    atBottomStateChange?: (isAtBottom: boolean) => void;
    className?: string;
  }

  const VirtuosoMock = React.forwardRef<unknown, VirtuosoMockProps>(function VirtuosoMock(
    props,
    ref
  ) {
    const {
      data,
      itemContent,
      components,
      scrollerRef,
      followOutput,
      atBottomStateChange,
      className
    } = props;

    const handle = React.useMemo(() => {
      const h = new VirtuosoHandleStub();
      instances.push(h);
      return h;
    }, []);
    React.useImperativeHandle(ref, () => handle, []);

    const scrollerDomRef = React.useRef<HTMLDivElement | null>(null);
    const setScrollerRef = React.useCallback(
      (el: HTMLDivElement | null) => {
        scrollerDomRef.current = el;
        handle.scroller = el;
        scrollerRef?.(el);
      },
      [handle, scrollerRef]
    );

    // atBottomStateChange / followOutput：scroll 事件 + 50ms 节流（与真实 Virtuoso 一致）
    const lastAtBottomRef = React.useRef(true);
    React.useEffect(() => {
      const el = scrollerDomRef.current;
      if (!el) return;
      let timer: ReturnType<typeof setTimeout> | null = null;
      const onScroll = () => {
        const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(() => {
          timer = null;
          if (isAtBottom !== lastAtBottomRef.current) {
            lastAtBottomRef.current = isAtBottom;
            atBottomStateChange?.(isAtBottom);
          }
          followOutput?.(isAtBottom);
        }, 50);
      };
      el.addEventListener("scroll", onScroll);
      return () => {
        el.removeEventListener("scroll", onScroll);
        if (timer !== null) clearTimeout(timer);
      };
    }, [atBottomStateChange, followOutput, scrollerRef]);

    const ListComp = (components?.List ?? undefined) as React.ComponentType | undefined;
    const FooterComp = (components?.Footer ?? undefined) as React.ComponentType | undefined;
    const items = (data ?? []).map((item, index) => (
      <React.Fragment key={(item as { key?: string }).key ?? String(index)}>
        {itemContent?.(index, item)}
      </React.Fragment>
    ));

    return (
      <div className={className ?? "h-full"}>
        <div data-testid="virtuoso-scroller" ref={setScrollerRef} className="virtuoso-scroller">
          {ListComp ? <ListComp>{items}</ListComp> : items}
          {FooterComp ? <FooterComp /> : null}
        </div>
      </div>
    );
  });
  VirtuosoMock.displayName = "VirtuosoMock";

  return { Virtuoso: VirtuosoMock };
});

function makeMessage(
  id: string,
  role: "user" | "assistant",
  content: string,
  extra: Partial<Message> = {}
): Message {
  return {
    id,
    role,
    content,
    status: role === "user" ? "sent" : "done",
    createdAt: "2026-08-09T12:00:00Z",
    updatedAt: "2026-08-09T12:00:00Z",
    ...extra
  } as Message;
}

function makeStep(seq: number, status: AgentExecutionStep["status"]): AgentExecutionStep {
  return { stepId: `s-${seq}`, seq, phase: "tool", status, plan: 1, title: `步骤${seq}` };
}

function renderList(messages: Message[], extraProps: Partial<{ sessionKey: string | null }> = {}) {
  useChatStore.setState({ recommendReveal: null });
  return render(
    <MessageList messages={messages} isLoading={false} isStreaming={false} {...extraProps} />
  );
}

function findScroller(): HTMLElement | null {
  return document.querySelector('[data-testid="virtuoso-scroller"]');
}

async function settle(ms = 300) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/**
 * 接管 scroller 的滚动度量（jsdom 无布局，全为 0）。
 * 返回 { setTop, getTop, writes }：writes 记录一切程序对 scrollTop 的写入。
 */
function mockScrollMetrics(
  scroller: HTMLElement,
  opts: { scrollHeight: number; clientHeight: number; offsetHeight?: number; initialTop?: number }
) {
  let top = opts.initialTop ?? 0;
  const writes: number[] = [];
  Object.defineProperty(scroller, "scrollTop", {
    configurable: true,
    get: () => top,
    set: (v: number) => {
      writes.push(v);
      top = v;
    }
  });
  Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: opts.scrollHeight });
  Object.defineProperty(scroller, "clientHeight", { configurable: true, value: opts.clientHeight });
  if (opts.offsetHeight !== undefined) {
    Object.defineProperty(scroller, "offsetHeight", { configurable: true, value: opts.offsetHeight });
  }
  return {
    setTop: (v: number) => {
      top = v;
    },
    getTop: () => top,
    writes
  };
}

function lastObserver(): MockResizeObserver {
  return MockResizeObserver.instances[MockResizeObserver.instances.length - 1];
}

/**
 * 接管 requestAnimationFrame：捕获回调但不真正调度（spy 默认 call-through 会让
 * jsdom 的 rAF 队列在 ~16ms 后再执行一次回调，造成「双触发」假象）。
 * 返回 { spy, captured }：captured 为按顺序记录的帧回调，测试手动执行。
 */
function spyRaf() {
  const captured: FrameRequestCallback[] = [];
  const spy = vi.spyOn(window, "requestAnimationFrame").mockImplementation(
    (cb: FrameRequestCallback) => {
      captured.push(cb);
      return 1;
    }
  );
  return { spy, captured };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  MockResizeObserver.instances = [];
  virtuosoMock.instances.length = 0;
});

describe("MessageList 用户滚离", () => {
  it("wheel 向上滚离 → 出现「回到底部」；同轮内容增长不重新贴底", async () => {
    const u1 = makeMessage("u1", "user", "牛肉和什么商品适合搭配推荐？");
    const a1 = makeMessage("a1", "assistant", "推荐根茎类蔬菜。");
    const { rerender } = renderList([u1, a1]);
    const scroller = findScroller()!;
    expect(scroller).not.toBeNull();
    // 等 Virtuoso 初始 LAST 定位（jsdom 中为 no-op）完成，再接管滚动度量
    await settle();

    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // 真实用户输入：wheel 向上滚 → 距底 800-100-300=400 > 40 → detached；
    // 随后浏览器产生 scroll 事件 → Virtuoso 报 atBottom=false
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80); // atBottomStateChange 有 50ms 节流

    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 同轮内容增长（token 原地更新，turns 数不变）：不贴底、不重新附着
    m.writes.length = 0;
    rerender(
      <MessageList
        messages={[u1, { ...a1, content: `${a1.content}（回答继续变长……）` }]}
        isLoading={false}
        isStreaming={false}
      />
    );
    await settle(120);

    expect(m.writes).toEqual([]);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("touchmove 与键盘上翻同样是真实滚离输入；点击「回到底部」后重新附着", async () => {
    const messages = [
      makeMessage("u1", "user", "问题"),
      makeMessage("a1", "assistant", "回答")
    ];
    renderList(messages);
    const scroller = findScroller()!;
    await settle();

    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // touchmove 滚离
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new Event("touchmove", { bubbles: true }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 点击回到底部 → detached 重置（滚动由 scrollToIndex smooth 负责）→ 按钮隐藏
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    // 键盘 PageUp 再次滚离（atBottom 仍为 false，无需再派发 scroll）
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true }));
    });
    await settle(30);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });
});

describe("MessageList 程序布局变化 ≠ 滚离", () => {
  it("仅更新 assistant 的 agentSteps（Timeline 高度变化）不触发滚离", async () => {
    const u1 = makeMessage("u1", "user", "问题");
    const a1 = makeMessage("a1", "assistant", "回答", { agentSteps: [] });
    const { rerender } = renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();

    const scrollToSpy = vi.spyOn(Element.prototype, "scrollTo");
    rerender(
      <MessageList
        messages={[
          u1,
          { ...a1, agentSteps: [makeStep(1, "completed"), makeStep(2, "completed"), makeStep(3, "running")] }
        ]}
        isLoading={false}
        isStreaming={false}
      />
    );
    await settle(120);

    // 无 wheel/touch/keydown → detached 保持 false → 按钮不出现
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
    expect(scrollToSpy).not.toHaveBeenCalled();
  });
});

describe("MessageList 新消息发送", () => {
  it("turns 增长（新 user turn）→ 重置滚离并贴底（无 timer）", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    const u2 = makeMessage("u2", "user", "问题二");
    const a2 = makeMessage("a2", "assistant", "回答二");
    const { rerender } = renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();

    // offsetHeight 让 Virtuoso 的 scrollTo 落地路径（jsdom 中默认 0 会提前 return）可执行
    mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300, offsetHeight: 300 });

    // 先滚离
    act(() => {
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 发送新消息 → turns 1→2：detached 重置（按钮消失）+ 立即贴底一次（scrollToIndex，无 timer）
    rerender(<MessageList messages={[u1, a1, u2, a2]} isLoading={false} isStreaming={false} />);
    await settle(50);

    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });
});

describe("MessageList 历史加载", () => {
  it("渲染 20 轮初始位于底部，无遗留 120/240/900ms 补滚 timer", async () => {
    const messages: Message[] = [];
    for (let i = 0; i < 20; i++) {
      messages.push(makeMessage(`u${i}`, "user", `问题${i}`, { turnId: i + 1 }));
      messages.push(makeMessage(`a${i}`, "assistant", `回答${i}`, { turnId: i + 1 }));
    }

    const spy = vi.spyOn(window, "setTimeout");
    renderList(messages);
    // jsdom 无布局，Virtuoso 初始 LAST 定位不依赖我们的代码；
    // 验证旧版 120/240/900ms 多段补滚 timer 已删除（Virtuoso 内部仅剩其自身的节流/防抖 timer）
    await settle(50);

    const delays = spy.mock.calls.map(([, delay]) => (typeof delay === "number" ? delay : NaN));
    expect(delays.some((d) => d === 120 || d === 240 || d === 900)).toBe(false);
    spy.mockRestore();

    // 初始 atBottom：挂载即报到底（不出现「回到底部」按钮）
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
    // 无任何 scrollTop 直赋补滚（jsdom 下 Virtuoso 初始定位不写 scrollTop）
    const scroller = findScroller();
    expect(scroller).not.toBeNull();
    expect(scroller!.scrollTop).toBe(0);
  });
});

describe("MessageList QuestionRail 已移除", () => {
  it("渲染后无 rail 相关节点", async () => {
    const messages = [
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("u3", "user", "问题三"),
      makeMessage("a3", "assistant", "回答三")
    ];
    renderList(messages);
    await settle(50);

    // QuestionRail 的滚动列表类与「问题文本 aria-label」按钮均不应存在
    expect(document.querySelector(".sidebar-scroll")).toBeNull();
    expect(document.querySelector('[aria-label="问题一"]')).toBeNull();
  });
});

describe("MessageList Latest Turn ResizeObserver", () => {
  it("新一轮 append：贴底一次 scrollToIndex，observer 重建并观察新的最新 Turn", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    const u2 = makeMessage("u2", "user", "问题二");
    const a2 = makeMessage("a2", "assistant", "回答二");
    const { rerender } = renderList([u1, a1]);
    await settle();

    // 挂载后：observer 已观察最新 Turn 的容器
    const firstObserver = lastObserver();
    expect(firstObserver.els).toHaveLength(1);
    expect(firstObserver.els[0]).toBeInstanceOf(HTMLDivElement);
    const firstEl = firstObserver.els[0];

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // 一轮完成 → append 第二个 Turn
    rerender(<MessageList messages={[u1, a1, u2, a2]} isLoading={false} isStreaming={false} />);
    await settle();

    // 新消息发送：恰好一次 scrollToIndex 贴底（behavior 默认 auto，无 timer）
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 1, align: "end" });

    // 最新 Turn 元素变化 → 旧 observer disconnect，新 observer 观察新元素
    const latestObserver = lastObserver();
    expect(latestObserver).not.toBe(firstObserver);
    expect(firstObserver.disconnectCount).toBe(1);
    expect(latestObserver.els).toHaveLength(1);
    expect(latestObserver.els[0]).toBeInstanceOf(HTMLDivElement);
    expect(latestObserver.els[0]).not.toBe(firstEl);
  });

  it("最新 Turn 高度变化（未滚离）→ rAF 合并后调用 autoscrollToBottom", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    await settle();

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const autoSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "autoscrollToBottom");

    // Timeline/正文高度增长（observer 回调）→ 调度一帧
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);

    // 帧回调执行 → Virtuoso.autoscrollToBottom 被调用
    act(() => {
      captured[0](0);
    });
    expect(autoSpy).toHaveBeenCalledTimes(1);
  });

  it("同一帧多次高度变化 → rAF 合并，autoscrollToBottom 每帧只调用一次", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    await settle();

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const autoSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "autoscrollToBottom");

    // 同一帧内多次 resize（Timeline 每步 + 正文每 chunk）→ 只调度一次 rAF
    act(() => {
      observer.trigger();
      observer.trigger();
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);

    act(() => {
      captured[0](0);
    });
    expect(autoSpy).toHaveBeenCalledTimes(1);

    // 下一帧再次增长 → 重新调度并再次触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(2);
    act(() => {
      captured[1](0);
    });
    expect(autoSpy).toHaveBeenCalledTimes(2);
  });

  it("wheel 上翻滚离后，Turn 高度增长不再触发 autoscrollToBottom；按钮出现", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const autoSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "autoscrollToBottom");

    // 未滚离时：高度变化正常触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(autoSpy).toHaveBeenCalledTimes(1);

    // 用户向上滚（wheel deltaY < 0）→ detached=true → 按钮出现
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 滚离后 Turn 继续增长 → 不调度 rAF、不 autoscroll（按钮保持可见）
    rAFSpy.mockClear();
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).not.toHaveBeenCalled();
    expect(autoSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("点击「回到底部」重新附着后，Turn 高度增长恢复 autoscrollToBottom", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // 先滚离
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const autoSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "autoscrollToBottom");

    // detached 期间：高度增长不触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).not.toHaveBeenCalled();

    // 点击「回到底部」→ detached=false → 按钮消失
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    // 重新附着后：高度增长恢复触发 autoscrollToBottom
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(autoSpy).toHaveBeenCalledTimes(1);
  });

  it("组件卸载 → Latest Turn observer 被 disconnect", async () => {
    const { unmount } = renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一")
    ]);
    await settle();

    const observer = lastObserver();
    expect(observer.disconnectCount).toBe(0);

    act(() => {
      unmount();
    });
    expect(observer.disconnectCount).toBe(1);
  });
});
