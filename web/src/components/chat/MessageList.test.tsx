import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageList } from "@/components/chat/MessageList";
import { useChatStore } from "@/stores/chatStore";
import type { AgentExecutionStep, Message } from "@/types";

// jsdom 没有 Element.scrollTo / scrollBy。Virtuoso 的 scrollToIndex 落地依赖它们，
// 这里补最小实现，供 mockScrollMetrics 之外的路径（如回到底部按钮）使用。
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = function (
    this: Element,
    leftOrOptions?: number | ScrollToOptions,
    top?: number
  ) {
    const nextTop = typeof leftOrOptions === "number" ? top ?? 0 : leftOrOptions?.top ?? 0;
    (this as HTMLElement).scrollTop = nextTop;
  };
}
if (typeof Element.prototype.scrollBy !== "function") {
  Element.prototype.scrollBy = function (
    this: Element,
    leftOrOptions?: number | ScrollToOptions,
    top?: number
  ) {
    const nextTop = typeof leftOrOptions === "number" ? top ?? 0 : leftOrOptions?.top ?? 0;
    (this as HTMLElement).scrollTop += nextTop;
  };
}

// 注意：jsdom 无真实布局，真实 Virtuoso 不会渲染虚拟化条目（条目渲染由
// ChatTurnItem.test 直接覆盖）。本文件把 react-virtuoso 替换为可控 mock：
// 渲染全部条目（复用 itemContent，Latest Turn ResizeObserver 因此能拿到
// 真实 DOM 节点）、提供 data-testid="virtuoso-scroller"、可 spy 的
// VirtuosoHandle（scrollToIndex / scrollIntoView；autoscrollToBottom 已废弃
// 不再被调用，stub 仅保留兼容）以及 atBottomStateChange / followOutput 回调
// （scroll 事件 + 50ms 节流，与真实行为一致）。滚动度量仍通过 mockScrollMetrics
// 在 scroller 实例上注入。

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
    /** 最近一次 followOutput 的返回值（供断言「只看 detached、不依赖数学底部」） */
    lastFollowOutput: false | "auto" | undefined = undefined;
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
    /** 推荐面板展开滚动：与 scrollToIndex 同构，测试只断言「被调用 + 参数」 */
    scrollIntoView(opts: { index: number; align?: string; behavior?: ScrollBehavior }) {
      const el = this.scroller;
      if (!el || el.offsetHeight === 0) return;
      el.scrollTo({ top: el.scrollHeight, behavior: opts.behavior });
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
    rangeChanged?: (range: { startIndex: number; endIndex: number }) => void;
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
      rangeChanged,
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

    // atBottomStateChange / followOutput / rangeChanged：scroll 事件 + 50ms 节流
    // （与真实 Virtuoso 一致；rangeChanged 的 startIndex 模拟为 scrollTop/100）
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
          rangeChanged?.({
            startIndex: Math.round(el.scrollTop / 100),
            endIndex: Math.round(el.scrollTop / 100) + 5
          });
          if (isAtBottom !== lastAtBottomRef.current) {
            lastAtBottomRef.current = isAtBottom;
            atBottomStateChange?.(isAtBottom);
          }
          handle.lastFollowOutput = followOutput?.(isAtBottom);
        }, 50);
      };
      el.addEventListener("scroll", onScroll);
      return () => {
        el.removeEventListener("scroll", onScroll);
        if (timer !== null) clearTimeout(timer);
      };
    }, [atBottomStateChange, followOutput, rangeChanged, scrollerRef]);

    const ListComp = (components?.List ?? undefined) as
      | React.ComponentType<React.PropsWithChildren>
      | undefined;
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

    // 触屏方向滚离：手指下滑（touches clientY 增大 → delta>0）→ 页面上滚 → detached
    act(() => {
      const start = new Event("touchstart", { bubbles: true, cancelable: true });
      Object.defineProperty(start, "touches", { value: [{ clientY: 100 }] });
      scroller.dispatchEvent(start);
      const move = new Event("touchmove", { bubbles: true, cancelable: true });
      Object.defineProperty(move, "touches", { value: [{ clientY: 200 }] });
      scroller.dispatchEvent(move);
      m.setTop(100);
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

    // 新消息发送：恰好一次 scrollToIndex 贴底（behavior auto，无 timer）
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 1, align: "end", behavior: "auto" });

    // 最新 Turn 元素变化 → 旧 observer disconnect，新 observer 观察新元素
    const latestObserver = lastObserver();
    expect(latestObserver).not.toBe(firstObserver);
    expect(firstObserver.disconnectCount).toBe(1);
    expect(latestObserver.els).toHaveLength(1);
    expect(latestObserver.els[0]).toBeInstanceOf(HTMLDivElement);
    expect(latestObserver.els[0]).not.toBe(firstEl);
  });

  it("最新 Turn 高度变化（未滚离）→ rAF 合并后 scrollToIndex(last, end, auto)", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    await settle();

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // Timeline/正文高度增长（observer 回调）→ 调度一帧
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);

    // 帧回调执行 → scrollToIndex(last, align: end, behavior: auto)
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 0, align: "end", behavior: "auto" });
  });

  it("同一帧多次高度变化 → rAF 合并，scrollToIndex 每帧只调用一次", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    await settle();

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

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
    expect(scrollSpy).toHaveBeenCalledTimes(1);

    // 下一帧再次增长 → 重新调度并再次触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(2);
    act(() => {
      captured[1](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(2);
  });

  it("上一轮 detached=true → 发送 Turn 2：detachedRef 同步复位（不等 render），首个 ResizeObserver 回调即恢复 scrollToIndex", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    const u2 = makeMessage("u2", "user", "问题二");
    const a2 = makeMessage("a2", "assistant", "回答二");
    const { rerender } = renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();

    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    // 上一轮真实滚离（wheel 上翻）→ detached=true → 按钮出现
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    // 发送 Turn 2：新 Turn effect 在 act 内同步执行完毕——detachedRef 已被同步
    // 置 false（不等 render），并立即贴底一次
    rerender(<MessageList messages={[u1, a1, u2, a2]} isLoading={false} isStreaming={false} />);
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 1, align: "end", behavior: "auto" });

    // 新 Turn 的 ResizeObserver 已重建；触发其高度变化：若 detachedRef 未同步
    // 复位会被跳过（不调度 rAF）——复位成功则应恢复 scrollToIndex
    scrollSpy.mockClear();
    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 1, align: "end", behavior: "auto" });
    // 重新附着：按钮消失
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });

  it("wheel 上翻滚离后，Turn 高度增长不再触发 scrollToIndex；按钮出现", async () => {
    renderList([makeMessage("u1", "user", "问题一"), makeMessage("a1", "assistant", "回答一")]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // 未滚离时：高度变化正常触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 0, align: "end", behavior: "auto" });

    // 用户向上滚（wheel deltaY < 0）→ detached=true → 按钮出现
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 滚离后 Turn 继续增长 → 不调度 rAF、不 scrollToIndex（按钮保持可见）
    rAFSpy.mockClear();
    scrollSpy.mockClear();
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).not.toHaveBeenCalled();
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("点击「回到底部」→ detachedRef 同步 false + scrollToIndex smooth；重新附着后高度增长恢复 scrollToIndex", async () => {
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
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // detached 期间：高度增长不触发
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).not.toHaveBeenCalled();

    // 点击「回到底部」→ detachedRef 同步 false（先于滚动）+ scrollToIndex smooth → 按钮消失
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 0, align: "end", behavior: "smooth" });
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    // 重新附着后：高度增长恢复触发 scrollToIndex
    scrollSpy.mockClear();
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 0, align: "end", behavior: "auto" });
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

describe("MessageList detached 状态机（只由用户意图修改）", () => {
  it("未滚离时即使滚动位置不在底部，也不出现「回到底部」按钮", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();

    // scrollHeight 800 / clientHeight 300：初始 scrollTop 0 已距底 500，数学上不在底部
    mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // 没有 wheel/touch/keydown → detached=false → 按钮不出现
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });

  it("滚离（detached=true）后「回到底部」按钮出现", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("竞态：ResizeObserver 已调度 rAF 后用户 wheel 向上，随后 atBottomStateChange(true) 到来 → detached 保持 true，pending rAF 不滚", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300, offsetHeight: 300 });

    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // 1. ResizeObserver 已经调度一个 rAF（pending，尚未执行）
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);

    // 2. 用户 wheel 向上 → detached=true
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // 3. Virtuoso 程序性 atBottomStateChange(true) 到来（滚动/重测量的回调）
    act(() => {
      m.setTop(500);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // 4. 执行之前 pending 的 rAF：detached 仍为 true → 不得 scrollToIndex
    scrollSpy.mockClear();
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it("wheel 向上 + atBottom=true 后 token 到达（resize）→ 0 次自动贴底", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300, offsetHeight: 300 });

    const observer = lastObserver();
    const { spy: rAFSpy } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");

    // 用户 wheel 向上 → detached=true
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // atBottom=true（几何到底，但 detached 必须保持 true）
    act(() => {
      m.setTop(500);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // 下一批 token 到达 → resize：observer 回调看到 detached=true → 不调度 rAF、不滚
    // （先清零 wheel/atBottom 阶段已产生的 navigation rAF）
    rAFSpy.mockClear();
    scrollSpy.mockClear();
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).not.toHaveBeenCalled();
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it("程序滚动到接近底部（无用户输入）→ 不 reattach（防止旧闪动 Bug 回来）", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // wheel 向上 → detached=true
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 程序滚动到 bottomGap=50（≤ REATTACH_GAP 96）：只有 scroll 事件，无用户输入
    act(() => {
      m.setTop(450);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // 不能 reattach：按钮仍显示（detached 保持 true）
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("detached=true + wheel 向下滚到接近底部（bottomGap=50）→ 自动 reattach", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // wheel 向上 → detached=true → 按钮出现
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 用户明确向下滚：wheel down 后 bottomGap = 800-654-300 = 46 ≤ 96 → reattach
    act(() => {
      m.setTop(654);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });

  it("detached=true + wheel 向下但仍在历史区（bottomGap=200）→ 保持 detached", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 向下滚但距底仍 200px（> 96）→ 不 reattach，按钮保持
    act(() => {
      m.setTop(300);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });

  it("wheel 向下 reattach 后 → 下一次 Latest Turn resize 恢复自动贴底", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300, offsetHeight: 300 });

    // wheel 向上 → detached
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // wheel 向下到接近底部 → reattach（detached=false）
    act(() => {
      m.setTop(654);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);

    // 下一次 streaming 内容增长（resize）→ 看到 detached=false → scrollToIndex(last, end)
    const observer = lastObserver();
    const { spy: rAFSpy, captured } = spyRaf();
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    act(() => {
      observer.trigger();
    });
    expect(rAFSpy).toHaveBeenCalledTimes(1);
    act(() => {
      captured[0](0);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 0, align: "end", behavior: "auto" });
  });
});

describe("MessageList 间距与 Footer", () => {
  it("List 容器无 space-y-7 / pb-8（底部呼吸改由最后 item 承担）", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二")
    ]);
    await settle(50);

    // Footer 已删除后，List 容器是 scroller 的唯一子元素
    const scroller = findScroller()!;
    const listEl = scroller.firstElementChild as HTMLElement;
    expect(listEl.className).not.toContain("space-y-7");
    // 底部呼吸空间不再属于 List 容器：容器 padding 不属于任何 item 的可测量高度，
    // 会让 scrollToIndex(align: "end") 与真底有偏差
    expect(listEl.className).not.toContain("pb-8");

    // Turn 间距由 ChatTurnItem 最外层 pb-7 承担（item padding 而非 margin）
    const turnBox = document.querySelector('[data-message-id="u1"]')!.parentElement!;
    expect(turnBox.className).toContain("pb-7");
    // 最后 item 多出 pb-8 作为底部呼吸空间（属于 item 可测量高度）
    const lastTurnBox = document.querySelector('[data-message-id="a2"]')!.parentElement!;
    expect(lastTurnBox.className).toContain("pb-8");
  });

  it("Footer 已移除（无 h-8 占位）；「回到底部」后重新附着，followOutput 恢复 auto", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    renderList([u1, a1]);
    const scroller = findScroller()!;
    await settle();

    // 无 h-8 占位 Footer（底部呼吸由最后 item 的 padding 承担）
    expect(scroller.querySelector('[aria-hidden="true"].h-8')).toBeNull();
    expect(scroller.querySelector(".h-8")).toBeNull();

    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // 回到底部 → 显式重置 detached（按钮消失）；随后滚动位置虽不在数学底部，
    // detached 保持 false（几何回调无权改回），不出现按钮
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });
});

describe("MessageList 推荐问题展开（Virtuoso scrollIntoView）", () => {
  it("recommendReveal 命中消息 → scrollIntoView({index, smooth, end})，且无 100/420ms 补滚 timer", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    const u2 = makeMessage("u2", "user", "问题二");
    const a2 = makeMessage("a2", "assistant", "回答二");
    renderList([u1, a1, u2, a2]);
    await settle(50);

    const spy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollIntoView");
    const timerSpy = vi.spyOn(window, "setTimeout");

    act(() => {
      useChatStore.setState({ recommendReveal: { id: "a2" } });
    });

    // 命中第 2 个 turn（index 1），smooth 滚到末尾对齐
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ index: 1, behavior: "smooth", align: "end" });

    // 不再有旧的 100/420ms 补滚 timer
    const delays = timerSpy.mock.calls.map(([, delay]) =>
      typeof delay === "number" ? delay : NaN
    );
    expect(delays.some((d) => d === 100 || d === 420)).toBe(false);
    timerSpy.mockRestore();
  });

  it("recommendReveal 指向不存在的消息 → 不调用 scrollIntoView", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一")
    ]);
    await settle(50);

    const spy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollIntoView");
    act(() => {
      useChatStore.setState({ recommendReveal: { id: "ghost" } });
    });

    expect(spy).not.toHaveBeenCalled();
  });
});

describe("MessageList 对话导航刻度（Minimap）", () => {
  function renderFourTurns() {
    return renderList([
      makeMessage("u1", "user", "牛肉和什么商品适合搭配推荐？"),
      makeMessage("a1", "assistant", "推荐根茎类蔬菜。"),
      makeMessage("u2", "user", "那土豆呢？"),
      makeMessage("a2", "assistant", "土豆适合与牛肉炖煮。"),
      makeMessage("u3", "user", "周末有活动吗？"),
      makeMessage("a3", "assistant", "有周末生鲜专场。"),
      makeMessage("u4", "user", "怎么参加？"),
      makeMessage("a4", "assistant", "打开 App 首页即可参与。")
    ]);
  }

  /**
   * jsdom 无布局：为 scroller 与各 turn 锚点注入真实几何（高度不等，模拟长/短回答）。
   * scrollerHeight 缺省为 turn 总高；可单独指定以构造「阅读线落在 gap」的场景。
   */
  function mockTurnGeometry(scroller: HTMLElement, heights: number[], scrollerHeight?: number) {
    const turns = Array.from(scroller.querySelectorAll<HTMLElement>("[data-turn-index]"));
    turns.forEach((el, i) => {
      const top = heights.slice(0, i).reduce((a, b) => a + b, 0);
      el.getBoundingClientRect = () =>
        ({
          top,
          bottom: top + heights[i],
          height: heights[i],
          width: 100,
          left: 0,
          right: 100,
          x: 0,
          y: 0,
          toJSON: () => ({})
        }) as DOMRect;
    });
    const total = scrollerHeight ?? heights.reduce((a, b) => a + b, 0);
    scroller.getBoundingClientRect = () =>
      ({ top: 0, bottom: total, height: total, width: 300, left: 0, right: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  }

  function currentAttr(label: string): string | null {
    return screen.getByRole("button", { name: label }).getAttribute("aria-current");
  }

  /**
   * 为 user message anchor 注入视口几何（minimap 精准定位的目标）。
   * scroller rect 由 mockTurnGeometry 提供（top 0）。
   */
  function mockAnchorGeometry(scroller: HTMLElement, anchors: Record<number, { top: number; height: number }>) {
    const els = Array.from(scroller.querySelectorAll<HTMLElement>("[data-user-message-anchor]"));
    els.forEach((el, i) => {
      const spec = anchors[i];
      if (!spec) return;
      el.getBoundingClientRect = () =>
        ({
          top: spec.top,
          bottom: spec.top + spec.height,
          height: spec.height,
          width: 100,
          left: 0,
          right: 100,
          x: 0,
          y: 0,
          toJSON: () => ({})
        }) as DOMRect;
    });
  }

  /**
   * active 判定的锚点几何：内容坐标（contentTop）随 scrollTop 平移——
   * anchor 视口 top = contentTop - scrollTop（模拟真实滚动）。scroller rect
   * 高度 = clientHeight（可视高度，阅读线 = clientHeight * 0.35）。
   */
  function mockAnchorContent(scroller: HTMLElement, contentTops: number[], clientHeight: number) {
    const els = Array.from(scroller.querySelectorAll<HTMLElement>("[data-user-message-anchor]"));
    els.forEach((el, i) => {
      const contentTop = contentTops[i];
      if (contentTop === undefined) return;
      el.getBoundingClientRect = () => {
        const top = contentTop - scroller.scrollTop;
        return {
          top,
          bottom: top + 40,
          height: 40,
          width: 100,
          left: 0,
          right: 100,
          x: 0,
          y: 0,
          toJSON: () => ({})
        } as DOMRect;
      };
    });
    scroller.getBoundingClientRect = () =>
      ({
        top: 0,
        bottom: clientHeight,
        height: clientHeight,
        width: 300,
        left: 0,
        right: 300,
        x: 0,
        y: 0,
        toJSON: () => ({})
      }) as DOMRect;
  }

  it("turns < 4 不渲染 minimap；≥ 4 渲染每轮一根线", async () => {
    const { rerender } = renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一")
    ]);
    await settle(50);
    expect(screen.queryByRole("navigation", { name: "对话导航" })).not.toBeInTheDocument();

    rerender(
      <MessageList
        messages={[
          makeMessage("u1", "user", "问题一"),
          makeMessage("a1", "assistant", "回答一"),
          makeMessage("u2", "user", "问题二"),
          makeMessage("a2", "assistant", "回答二"),
          makeMessage("u3", "user", "问题三"),
          makeMessage("a3", "assistant", "回答三"),
          makeMessage("u4", "user", "问题四"),
          makeMessage("a4", "assistant", "回答四")
        ]}
        isLoading={false}
        isStreaming={false}
      />
    );
    await settle(50);
    expect(screen.getByRole("navigation", { name: "对话导航" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 4 轮对话" })).toBeInTheDocument();
  });

  it("布局未完成（scroller 高度 0）→ 不高亮任何轮（active=null）", async () => {
    renderFourTurns();
    // 不注入几何：jsdom rect 全 0 → 防御分支保持 null
    await settle(80);
    expect(
      screen.getAllByRole("button").every((b) => b.getAttribute("aria-current") === null)
    ).toBe(true);
  });

  it("User Anchor 最近判定：35% 阅读线距最近的用户问题锚点（回答高度不均不滞后）", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("u3", "user", "问题三"),
      makeMessage("a3", "assistant", "回答三"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    const scroller = findScroller()!;
    await settle();
    // user 锚点内容坐标：0 / 320 / 540 / 680（turn0 assistant 280 很长）
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });

    act(() => {
      m.setTop(360); // bottomGap = 60 > 48 → anchor 判定
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // readY = 105；anchor 视口 top = -360 / -40 / 180 / 320 → 距 105 最近的是 turn2（第 3 轮）。
    // 旧算法：105 在 turn0 的 assistant 区域 → 会错误高亮第 1 轮
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 1 轮对话")).not.toBe("true");
  });

  it("第一轮超长回答：最近的用户锚点仍是第一轮时不提前跳到下一轮", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("u3", "user", "问题三"),
      makeMessage("a3", "assistant", "回答三"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    const scroller = findScroller()!;
    await settle();
    // turn0 超长（turn1 的 user 在 500 才出现），turn2/3 在 900/1200
    mockAnchorContent(scroller, [0, 500, 900, 1200], 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 1300, clientHeight: 300 });

    act(() => {
      m.setTop(100); // bottomGap = 900 > 48
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // readY = 105；anchor 视口 top = -100 / 400 / 800 / 1100 → 最近 turn0（第 1 轮）
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 2 轮对话")).not.toBe("true");
  });

  it("N → N-1 → N-2 顺序：底部上滚后逐级切到上一轮（不跳级）", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("u3", "user", "问题三"),
      makeMessage("a3", "assistant", "回答三"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    const scroller = findScroller()!;
    await settle();
    // user 40 + assistant 280/180/100/60（评审场景）
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });

    // 底部：bottomGap = 0 → 最后一轮
    act(() => {
      m.setTop(420);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 向上 60px：bottomGap = 60 > 48 → anchor 判定 → 距 readY 105 最近是 turn2（倒数第二）
    act(() => {
      m.setTop(360);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 4 轮对话")).not.toBe("true");

    // 再向上：anchor 视口 top = -100 / 220 / 440 / 580 → 最近 turn1（倒数第三）
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 3 轮对话")).not.toBe("true");
  });

  it("bottom 双阈值：进入底部（≤24px）→ 最后一轮；已在最后一轮须离开 48px 外才交还", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("u3", "user", "问题三"),
      makeMessage("a3", "assistant", "回答三"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    const scroller = findScroller()!;
    await settle();
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });

    // 底部（gap 0）→ 最后一轮
    act(() => {
      m.setTop(420);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 小幅离开（gap 40，仍在 EXIT 48 内）→ 保持最后一轮（hysteresis，不闪）
    act(() => {
      m.setTop(380);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 离开到底部 60px（> 48）→ 交还 anchor 判定
    act(() => {
      m.setTop(360);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
  });

  it("PageUp 大滚动：允许直接跨多轮（邻接保护只约束小滚动）", async () => {
    renderList(
      Array.from({ length: 12 }, (_, i) => [
        makeMessage(`u${i}`, "user", `问题${i}`),
        makeMessage(`a${i}`, "assistant", `回答${i}`)
      ]).flat()
    );
    const scroller = findScroller()!;
    await settle();
    // 每轮 user 40px 密集排列
    const contentTops = Array.from({ length: 12 }, (_, i) => i * 40);
    mockAnchorContent(scroller, contentTops, 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 700, clientHeight: 300 });

    act(() => {
      m.setTop(0); // bottomGap = 400 > 48
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // readY = 105；anchor tops 0..440 → 距 105 最近 turn3（120）→ 第 4 轮
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // PageUp 一次 200px（delta > 60）：允许从第 4 轮直接跳到第 7 轮（anchor 240 距 105 最近）
    act(() => {
      m.setTop(200);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // tops = i*40 - 200 → 距 105 最近 turn8（320-200=120，dist 15）→ 第 9 轮
    // 直接断言已跨多轮（小滚动 ±1 保护不限制大滚动）
    expect(currentAttr("跳转到第 4 轮对话")).not.toBe("true");
    expect(currentAttr("跳转到第 9 轮对话")).toBe("true");
  });

  it("小滚动邻接保护：候选跨多轮且滚动量小 → 最多切 ±1 轮", async () => {
    renderList(
      Array.from({ length: 6 }, (_, i) => [
        makeMessage(`u${i}`, "user", `问题${i}`),
        makeMessage(`a${i}`, "assistant", `回答${i}`)
      ]).flat()
    );
    const scroller = findScroller()!;
    await settle();
    mockAnchorContent(scroller, [0, 40, 80, 120, 140, 155], 300);
    const m = mockScrollMetrics(scroller, { scrollHeight: 400, clientHeight: 300 });

    // 先到第 4 轮（turn3）：scrollTop 0 → readY 105 距 turn3（120）最近
    act(() => {
      m.setTop(0);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 移除 turn4 的 anchor（模拟未连接）→ candidate 会跳过 turn4
    const anchors = Array.from(scroller.querySelectorAll<HTMLElement>("[data-user-message-anchor]"));
    anchors[4]!.remove();

    // 小滚动 50px（< 60）：candidate 跳到 turn5（视口 top 105 距 readY 0，明显最近），
    // |5-3| = 2 > 1 → 邻接保护 clamp 到 turn4（第 5 轮），不允许直接第 6 轮
    act(() => {
      m.setTop(50);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 5 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 6 轮对话")).not.toBe("true");
  });

  it("点击某根线（anchor 已 mounted）→ 精准 scrollBy 定位到 User Anchor，不经 Virtuoso；detached=true", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    // 第 3 轮 user anchor 视口 top = 250
    mockAnchorGeometry(scroller, { 2: { top: 250, height: 40 } });

    // 制造 atBottom=false（滚动事件节流后上报），但 detached 仍 false → 按钮不显示
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));

    // anchor 已 mounted → 不经过 Virtuoso（不调用 scrollToIndex）
    expect(scrollSpy).not.toHaveBeenCalled();
    // 精准定位：delta = 250 - 0 - 24 = 226 → 用户问题落到 viewport 顶部 + 24px
    expect(m.getTop()).toBe(226);
    // detached=true → 回到底部按钮出现；selected 立即高亮
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
  });

  it("点击只执行一次精准 scrollBy；导航期间 scroll 事件不反复更新 active（selected 保持）", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    mockAnchorGeometry(scroller, { 1: { top: 50, height: 40 } });

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 2 轮对话" }));
    // 只执行一次精准定位（scrollBy），不经 Virtuoso
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(m.getTop()).toBe(50 - 24);
    // 用户显式选择立即高亮（selected 优先），不依赖几何
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");

    // 导航定位触发的中间 scroll：selected 保持，高亮不被中间 viewport 位置抢走
    act(() => {
      m.setTop(300);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
  });

  it("尾部点击（目标已可见、无滚动空间）：selected 立即高亮，bottom override 抢不回去；真实滚动后才交还", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    // 已滚到底：bottomGap = 800-500-300 = 0 → 几何 active = 最后一轮（第 4 根）
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    mockAnchorGeometry(scroller, { 2: { top: 250, height: 40 } });
    act(() => {
      m.setTop(500);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 点击倒数第二根（第 3 轮）：立即高亮 + anchor 精准定位
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 4 轮对话")).not.toBe("true");

    // 即使随后 atBottomStateChange(true) / 几何重算（activeTurnIndex 后台回到 last）：
    // selected 优先，第 3 根保持高亮
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 4 轮对话")).not.toBe("true");

    // 真实用户滚动（wheel）→ 清除 selected，交还几何 active
    act(() => {
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // 几何：仍在底部 → 第 4 根
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 3 轮对话")).not.toBe("true");
  });

  it("最后一根 marker 也定位到 User Anchor；「回到底部」才定位底部（smooth）+ 清除 selected", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    mockAnchorGeometry(scroller, { 1: { top: 50, height: 40 }, 3: { top: 330, height: 40 } });

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    // 历史轮：anchor 精准定位，不经 Virtuoso
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 2 轮对话" }));
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(m.getTop()).toBe(50 - 24);
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");

    // 最后一根（index 3）同样定位到最后一个 User Anchor，不是 conversation bottom
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 4 轮对话" }));
    expect(scrollSpy).not.toHaveBeenCalled();
    // scrollBy 累计：26（第一次）+ (330 - 24)（第二次）
    expect(m.getTop()).toBe(26 + 330 - 24);
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");

    // 滚离 → detached；点击「回到底部」→ scrollToIndex(end, smooth) + 清除 selected
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 3, align: "end", behavior: "smooth" });
    // selected 已清除 → 高亮交还几何 active（wheel 时阅读线在 turn1 → 第 2 轮）
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 4 轮对话")).not.toBe("true");
  });

  it("anchor 未 mounted（孤立 assistant turn 无用户消息）→ Virtuoso materialize（scrollToIndex start）", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("a3", "assistant", "孤立回答（无用户消息）"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    await settle();
    const scroller = findScroller()!;
    mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    // 第 3 轮是孤立 assistant：无 user anchor → 走 Virtuoso materialize
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 2, align: "start", behavior: "auto" });
    // selected 仍立即高亮
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
  });

  it("materialize 路径导航闭合：兜底 rAF 恢复 navigating，后续滚动 active 正常更新", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("a3", "assistant", "孤立回答（无用户消息）"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    await settle();
    const scroller = findScroller()!;
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });
    // turn2 无 user（孤立 assistant）→ 只有 3 个 anchor
    mockAnchorContent(scroller, [0, 320, 680], 300);

    // 远距离点击（无 anchor 的 turn）→ 兜底 rAF 完成导航
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    await settle(50);

    // 后续真实滚动：若 navigating 卡 true，active 将永不更新
    act(() => {
      m.setTop(100);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // readY = 105；anchor 视口 top = -100 / 220 / 580 → 最近 turn1 → 第 2 轮（active 已恢复更新）
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 3 轮对话")).not.toBe("true");
  });

  it("真实滚动后：先更新 active 再释放 selected（不闪旧 active）", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);

    // 旧 active：scrollTop 0 → anchor 视口 top 0..680 → 距 readY 105 最近 turn0 → 第 1 轮
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");

    // 点击第 3 轮 → selected 覆盖显示
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");

    // wheel 事件发生瞬间：selected 尚未释放（只打标记，等 scroll rAF）
    act(() => {
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
    });
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");

    // 浏览器滚动完成 → scroll rAF：先 updateActiveTurn，同一批更新里释放 selected
    act(() => {
      m.setTop(300);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // anchor 视口 top = -300 / 20 / 240 / 380 → 距 105 最近 turn1（20）→ 第 2 轮接管
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 3 轮对话")).not.toBe("true");
  });

  it("点击远距离后立即 wheel → pending 导航取消，materialize 完成不再拉回", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二"),
      makeMessage("a3", "assistant", "孤立回答（无用户消息）"),
      makeMessage("u4", "user", "问题四"),
      makeMessage("a4", "assistant", "回答四")
    ]);
    await settle();
    const scroller = findScroller()!;
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // 点击第 3 轮（孤立 turn：scrollToIndex 路径，pending=2）
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    // 用户立即 wheel（materialize 未完成）→ cancelPending
    act(() => {
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
    });

    // 兜底 rAF 执行：pending 已取消 → 不 scrollBy、不把页面拉回目标
    await settle(80);
    expect(m.getTop()).toBe(0);
    // selected 尚未释放（wheel 只打标记，等 scroll 后统一释放）→ 高亮保持
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
  });

  it("点击跳转不锁定 active：真实滚动（wheel）清除 selected 后，高亮跟随阅读线，手滚回第一轮自然更新", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);

    // 制造 atBottom=false（滚动事件节流后上报），但 detached 仍 false → 按钮不显示
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    // 点击第 4 轮（index 3）→ selected 立即高亮 + detached
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 4 轮对话" }));
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
    await settle(30); // 导航 rAF 解除导航锁

    // 真实滚动（wheel up）→ 清除 selected；scrollTop 300 → anchor 视口 top -300/20/240/380
    // → 距 readY 105 最近 turn1（20）→ 第 2 轮
    act(() => {
      m.setTop(300);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");

    // 用户手滚回第一轮：scrollTop 0 → anchor 视口 top 0/320/540/680 → 最近 turn0 → 第 1 轮
    act(() => {
      m.setTop(0);
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: -120 }));
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");
  });

  it("会话切换不继承上一会话 active：先清空（null），布局完成后按新会话计算", async () => {
    const mk = (prefix: string) => [
      makeMessage(`${prefix}u1`, "user", "问题一", { turnId: 1 }),
      makeMessage(`${prefix}a1`, "assistant", "回答一", { turnId: 1 }),
      makeMessage(`${prefix}u2`, "user", "问题二", { turnId: 2 }),
      makeMessage(`${prefix}a2`, "assistant", "回答二", { turnId: 2 }),
      makeMessage(`${prefix}u3`, "user", "问题三", { turnId: 3 }),
      makeMessage(`${prefix}a3`, "assistant", "回答三", { turnId: 3 }),
      makeMessage(`${prefix}u4`, "user", "问题四", { turnId: 4 }),
      makeMessage(`${prefix}a4`, "assistant", "回答四", { turnId: 4 })
    ];
    const { rerender } = renderList(mk("A"), { sessionKey: "sess-A" });
    await settle();
    const scroller = findScroller()!;
    mockAnchorContent(scroller, [0, 320, 540, 680], 300);
    mockScrollMetrics(scroller, { scrollHeight: 720, clientHeight: 300 });
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // 会话 A：scrollTop 0 → anchor 视口 top 0..680 → 距 readY 105 最近 turn0 → 第 1 轮
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");

    // 切换到会话 B：active 立即清空（null）→ 无任何高亮（绝不继承第 1 轮）
    rerender(<MessageList messages={mk("B")} isLoading={false} isStreaming={false} sessionKey="sess-B" />);
    await settle(30);
    expect(
      screen.getAllByRole("button").every((b) => b.getAttribute("aria-current") === null)
    ).toBe(true);

    // 布局完成（rAF 补算）：注入新几何 → 新会话 scrollTop 0 → 阅读线最近 turn0 → 第 1 轮
    const scrollerB = findScroller()!;
    mockAnchorContent(scrollerB, [0, 320, 540, 680], 300);
    mockScrollMetrics(scrollerB, { scrollHeight: 720, clientHeight: 300 });
    act(() => {
      scrollerB.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");
  });

  it("点击导航进入历史时 detached=true：AI 继续输出不拉回底部", async () => {
    const u1 = makeMessage("u1", "user", "问题一");
    const a1 = makeMessage("a1", "assistant", "回答一");
    const u2 = makeMessage("u2", "user", "问题二");
    const a2 = makeMessage("a2", "assistant", "回答二");
    const u3 = makeMessage("u3", "user", "问题三");
    const a3 = makeMessage("a3", "assistant", "回答三", { agentSteps: [] });
    const u4 = makeMessage("u4", "user", "问题四");
    const a4 = makeMessage("a4", "assistant", "回答四");
    const { rerender } = renderList([u1, a1, u2, a2, u3, a3, u4, a4]);
    const scroller = findScroller()!;
    await settle();
    mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });

    // 先制造 atBottom=false（滚动事件节流后上报），但 detached 仍 false → 按钮不显示
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    // 点击第 2 轮 marker（看历史）→ detached
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 2 轮对话" }));
    await settle(50);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    // AI 继续输出（同轮内容增长，turns 数不变）：不得自动拉回底部
    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    rerender(
      <MessageList
        messages={[u1, a1, u2, a2, u3, { ...a3, content: `${a3.content}（继续输出……）` }, u4, a4]}
        isLoading={false}
        isStreaming={false}
      />
    );
    await settle(120);
    expect(scrollSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
  });
});
