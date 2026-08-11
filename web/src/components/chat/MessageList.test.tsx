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
    /** 阅读线比例的数据来源：mock 返回空 ranges（组件回退均匀分布） */
    getState(
      cb: (s: { ranges: { startIndex: number; endIndex: number; size: number }[]; scrollTop: number }) => void
    ) {
      cb({ ranges: [], scrollTop: this.scroller?.scrollTop ?? 0 });
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

describe("MessageList followOutput（新语义：只看 detached，不依赖数学底部）", () => {
  it("未滚离（detached=false）时即使滚动位置不在底部，followOutput 也为 auto", async () => {
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

    const handle = virtuosoMock.instances[0]!;
    // 没有 wheel/touch/keydown → detached=false → followOutput="auto"（旧实现此处返回 false）
    expect(handle.lastFollowOutput).toBe("auto");
    // 未滚离 → 「回到底部」按钮不出现（按钮条件 detached && !atBottom）
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });

  it("滚离（detached=true）后 followOutput 为 false，且「回到底部」按钮出现", async () => {
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

    const handle = virtuosoMock.instances[0]!;
    expect(handle.lastFollowOutput).toBe(false);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
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

    // 回到底部 → 重新附着（按钮消失）；随后滚动位置虽不在数学底部，
    // followOutput 仍为 auto——对齐的就是真正的列表底，不再被 Footer 架空判定
    fireEvent.click(screen.getByRole("button", { name: "回到底部" }));
    await settle(50);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    const handle = virtuosoMock.instances[0]!;
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(handle.lastFollowOutput).toBe("auto");
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

describe("MessageList 对话导航 Minimap", () => {
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

  /** jsdom 无布局：为 scroller 与各 turn 锚点注入真实几何（高度不等，模拟长/短回答） */
  function mockTurnGeometry(scroller: HTMLElement, heights: number[]) {
    const turns = Array.from(
      scroller.querySelectorAll<HTMLElement>("[data-turn-index]")
    );
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
    const total = heights.reduce((a, b) => a + b, 0);
    scroller.getBoundingClientRect = () =>
      ({ top: 0, bottom: total, height: total, width: 300, left: 0, right: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  }

  function currentAttr(label: string): string | null {
    return screen.getByRole("button", { name: label }).getAttribute("aria-current");
  }

  it("turns < 4 不渲染 minimap；≥ 4 渲染一根线一轮", async () => {
    renderList([
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二"),
      makeMessage("a2", "assistant", "回答二")
    ]);
    await settle(50);
    // 2 轮 → 隐藏；再 append 到 4 轮 → 出现
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
    // 每轮一根线（4 轮 4 个跳转按钮，aria-label 带轮次）
    expect(screen.getByRole("button", { name: "跳转到第 1 轮对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳转到第 4 轮对话" })).toBeInTheDocument();
  });

  it("阅读线判定：视口顶部向下 30% 命中的轮次为当前轮（回答高度不均时不再滞后）", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();

    // 高度不均：turn0 50px（短答）、turn1 200px（长答）、turn2 80px、turn3 100px
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    // 初始（未滚动）：rect 全 0 时命中第 1 轮
    expect(currentAttr("跳转到第 1 轮对话")).toBe("true");

    // 滚动到阅读线落在 turn1（anchorY = 430*0.3 = 129 ∈ [50,250]）→ 第 2 轮高亮
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
    expect(currentAttr("跳转到第 1 轮对话")).not.toBe("true");

    // 继续滚动使阅读线落在 turn3（anchorY = 430*0.3 = 129 ∈ [330,430] → 需改变几何）
    mockTurnGeometry(scroller, [50, 200, 80, 100]);
    // 模拟内容上移：scroller 视口位置不变，turn 位置整体上移 300px
    const turns = Array.from(scroller.querySelectorAll<HTMLElement>("[data-turn-index]"));
    turns.forEach((el, i) => {
      const tops = [0, 50, 250, 330].map((v) => v - 300);
      const top = tops[i];
      el.getBoundingClientRect = () =>
        ({ top, bottom: top + [50, 200, 80, 100][i], height: [50, 200, 80, 100][i], width: 100, left: 0, right: 100, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
    });
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // anchorY 129 ∈ [30,110]（turn3 上移后）→ 第 4 轮
    expect(currentAttr("跳转到第 4 轮对话")).toBe("true");
  });

  it("点击某根线 → detached=true + scrollToIndex(start, smooth)，且立即高亮目标轮", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);

    // 制造 atBottom=false（滚动事件节流后上报），但 detached 仍 false → 按钮不显示
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();

    const scrollSpy = vi.spyOn(virtuosoMock.VirtuosoHandleStub.prototype, "scrollToIndex");
    // 点击「跳转到第 3 轮对话」（index 2）
    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));

    // 显式用户导航：scrollToIndex(start, smooth)；detached=true → 回到底部按钮出现；
    // 高亮立即锁定到目标轮（不等滚动落定）
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ index: 2, align: "start", behavior: "smooth" });
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");
  });

  it("点击跳转后锁定阅读线：smooth 滚动经过中间轮不抢高亮，滚动静止后恢复自动检测", async () => {
    renderFourTurns();
    const scroller = findScroller()!;
    await settle();
    const m = mockScrollMetrics(scroller, { scrollHeight: 800, clientHeight: 300 });
    mockTurnGeometry(scroller, [50, 200, 80, 100]);

    fireEvent.click(screen.getByRole("button", { name: "跳转到第 3 轮对话" }));
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");

    // smooth 滚动经过中间轮：scrollTop 变化 → 仍锁定，高亮不被抢
    act(() => {
      m.setTop(200);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");

    act(() => {
      m.setTop(300);
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    expect(currentAttr("跳转到第 3 轮对话")).toBe("true");

    // 滚动静止（scrollTop 不再变化）→ 解锁并校正阅读线
    act(() => {
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await settle(80);
    // 校正后 anchorY = 430*0.3 = 129 ∈ [50,250]（turn1）→ 第 2 轮
    expect(currentAttr("跳转到第 2 轮对话")).toBe("true");
  });
});
