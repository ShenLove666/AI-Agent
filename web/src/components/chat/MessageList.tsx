import * as React from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { ArrowDown } from "lucide-react";

import { MessageItem } from "@/components/chat/MessageItem";
import { QuestionRail, type QuestionRailItem } from "@/components/chat/QuestionRail";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";
import type { Message } from "@/types";

/** 距底部小于该距离视为"接近底部"，自动跟随滚动；用户滚离更远时暂停跟随 */
const NEAR_BOTTOM_THRESHOLD = 160;

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  isStreaming: boolean;
  sessionKey?: string | null;
}

export function MessageList({ messages, isLoading, isStreaming, sessionKey }: MessageListProps) {
  const virtuosoRef = React.useRef<VirtuosoHandle | null>(null);
  const scrollerRef = React.useRef<HTMLElement | null>(null);
  const lastSessionRef = React.useRef<string | null>(null);
  const pendingScrollRef = React.useRef(true);
  const settleTimerRef = React.useRef<number | null>(null);
  const prevStreamingRef = React.useRef(false);
  const recommendReveal = useChatStore((state) => state.recommendReveal);
  const initialTopMostItemIndex = React.useMemo(
    () => ({ index: "LAST" as const, align: "end" as const }),
    []
  );
  const [visibleEnd, setVisibleEnd] = React.useState(0);
  const [showScrollDown, setShowScrollDown] = React.useState(false);

  const isNearBottom = React.useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return true;
    return (
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <
      NEAR_BOTTOM_THRESHOLD
    );
  }, []);

  const userQuestions = React.useMemo<QuestionRailItem[]>(() => {
    const items: QuestionRailItem[] = [];
    messages.forEach((msg, flatIndex) => {
      if (msg.role !== "user") return;
      const text = msg.content.replace(/\s+/g, " ").trim();
      if (!text) return;
      items.push({ id: msg.id, flatIndex, text });
    });
    return items;
  }, [messages]);

  const activeQuestionId = React.useMemo(() => {
    if (userQuestions.length === 0) return null;
    let last: string | null = userQuestions[0].id;
    for (const q of userQuestions) {
      if (q.flatIndex <= visibleEnd) {
        last = q.id;
      } else {
        break;
      }
    }
    return last;
  }, [userQuestions, visibleEnd]);

  const handleSelectQuestion = React.useCallback((flatIndex: number) => {
    virtuosoRef.current?.scrollToIndex({
      index: flatIndex,
      align: "start",
      behavior: "smooth"
    });
  }, []);

  const handleRangeChanged = React.useCallback(
    (range: { startIndex: number; endIndex: number }) => {
      setVisibleEnd(range.endIndex);
    },
    []
  );

  const scrollToBottom = React.useCallback(() => {
    // 只用直接赋值：scrollToIndex（Virtuoso 内部异步状态机）与 scrollTop 赋值同时驱动
    // 会互相竞争，在 200ms 轮询下表现为视口上下闪动。scrollHeight 已含底部 padding/footer，
    // 直接赋值即可精确贴底。
    const scroller = scrollerRef.current;
    if (scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }, []);

  /**
   * 流式输出期间的贴底：默认仅在用户接近底部时跟随，
   * 用户滚离底部（往上翻历史）时暂停，避免抢滚动。
   * 传 { force: true } 用于明确的"回到底部"意图。
   */
  const stickToBottom = React.useCallback(
    (opts?: { force?: boolean }) => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      if (!opts?.force && !isNearBottom()) return;
      scroller.scrollTop = scroller.scrollHeight;
    },
    [isNearBottom]
  );

  // 滚动监听：用户滚离底部时显示"回到底部"浮动按钮
  // 滚离标记只在流式期间更新——输出结束后（Timeline 折叠等）的布局滚动不污染标记
  const userScrolledAwayRef = React.useRef(false);
  const isStreamingRef = React.useRef(isStreaming);
  isStreamingRef.current = isStreaming;
  const handleScrollerScrollRef = React.useRef<((event: Event) => void) | null>(null);
  if (handleScrollerScrollRef.current === null) {
    handleScrollerScrollRef.current = () => {
      const near = isNearBottomRef.current();
      setShowScrollDown((prev) => (prev === !near ? prev : !near));
      if (isStreamingRef.current) {
        userScrolledAwayRef.current = !near;
      }
    };
  }
  const isNearBottomRef = React.useRef(isNearBottom);
  isNearBottomRef.current = isNearBottom;

  React.useEffect(() => {
    const nextKey = sessionKey ?? "empty";
    if (lastSessionRef.current !== nextKey) {
      lastSessionRef.current = nextKey;
      pendingScrollRef.current = true;
      if (settleTimerRef.current) {
        window.clearTimeout(settleTimerRef.current);
        settleTimerRef.current = null;
      }
      // 会话加载贴底标记独立过期（不受后续 rerender 的 cleanup 干扰）
      settleTimerRef.current = window.setTimeout(() => {
        pendingScrollRef.current = false;
        settleTimerRef.current = null;
      }, 1500);
    }
  }, [sessionKey]);

  React.useEffect(() => {
    const wasStreaming = prevStreamingRef.current;
    prevStreamingRef.current = isStreaming;
    if (!wasStreaming && isStreaming) {
      // 刚发送消息时用户位于底部：重置滚离标记并强制贴底一次；此后的内容增长只接近底部才跟随
      userScrolledAwayRef.current = false;
      stickToBottom({ force: true });
      const timer = window.setTimeout(() => stickToBottom({ force: true }), 120);
      return () => window.clearTimeout(timer);
    }    if (wasStreaming && !isStreaming) {
      // 流式结束：流式期间用户未滚离 → 无条件贴底展示完整回答。
      // 多阶段重试覆盖 Timeline 折叠等后续布局变化；流式期间滚离过则不抢。
      if (!userScrolledAwayRef.current) {
        scrollToBottom();
        const timer = window.setTimeout(scrollToBottom, 120);
        const lateTimer = window.setTimeout(scrollToBottom, 360);
        const settleTimer = window.setTimeout(scrollToBottom, 900);
        return () => {
          window.clearTimeout(timer);
          window.clearTimeout(lateTimer);
          window.clearTimeout(settleTimer);
        };
      }
      return;
    }
    return;
  }, [isStreaming, stickToBottom, scrollToBottom]);

  // 流式期间跟随兜底：Virtuoso 的 followOutput 在 token 流中可能只触发一次，
  // 这里每 200ms 检查一次；仅当明显偏离底部（gap > 30px）才拉回，避免与
  // Virtuoso 内部布局/平滑动画互相拉扯造成闪动
  React.useEffect(() => {
    if (!isStreaming) return;
    const interval = window.setInterval(() => {
      if (userScrolledAwayRef.current) return;
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const gap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      if (gap > 30) {
        scroller.scrollTop = scroller.scrollHeight;
      }
    }, 200);
    return () => window.clearInterval(interval);
  }, [isStreaming]);

  React.useLayoutEffect(() => {
    if (!pendingScrollRef.current || isStreaming || isLoading || messages.length === 0) {
      return;
    }
    let attempts = 0;
    let rafId = 0;
    let active = true;
    const run = () => {
      scrollToBottom();
      attempts += 1;
      if (attempts < 3) {
        rafId = window.requestAnimationFrame(run);
      }
    };
    run();
    const timer = window.setTimeout(scrollToBottom, 240);
    const lateTimer = window.setTimeout(scrollToBottom, 900);
    const handleLoad = () => {
      if (active) {
        scrollToBottom();
      }
    };
    if (document.readyState === "complete") {
      handleLoad();
    } else {
      window.addEventListener("load", handleLoad, { once: true });
    }
    if (document.fonts?.ready) {
      document.fonts.ready.then(() => {
      if (active) {
        scrollToBottom();
      }
    });
  }
    return () => {
      active = false;
      window.cancelAnimationFrame(rafId);
      window.clearTimeout(timer);
      window.clearTimeout(lateTimer);
      window.removeEventListener("load", handleLoad);
    };
  }, [messages.length, isStreaming, isLoading, sessionKey]);

  React.useEffect(() => {
    return () => {
      if (settleTimerRef.current) {
        window.clearTimeout(settleTimerRef.current);
        settleTimerRef.current = null;
      }
    };
  }, []);

  // 展开推荐面板后把该条滚入视口：直接量真实 DOM 几何 不依赖 Virtuoso 的尺寸缓存
  // 缓存滞后会按面板展开前的旧高度欠滚 使变高的面板落到折叠线下 被输入框遮挡
  // 面板从骨架→问题会再次变高 故 ready 时会重新触发本效果按最终高度对齐 并在淡入动画结束后补一次精确贴齐
  React.useEffect(() => {
    if (!recommendReveal) return;
    const revealId = recommendReveal.id;
    const revealBottom = (behavior: ScrollBehavior) => {
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const el = scroller.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(revealId)}"]`);
      if (!el) return;
      const gap = 12; // 面板底部与输入框留出的呼吸间距
      const delta = el.getBoundingClientRect().bottom - (scroller.getBoundingClientRect().bottom - gap);
      // 仅在被遮挡时下滚露出 已完整可见则不上滚 避免打断阅读
      if (delta > 0) {
        scroller.scrollTo({ top: scroller.scrollTop + delta, behavior });
      }
    };
    const smoothTimer = window.setTimeout(() => revealBottom("smooth"), 100);
    const snapTimer = window.setTimeout(() => revealBottom("auto"), 420);
    return () => {
      window.clearTimeout(smoothTimer);
      window.clearTimeout(snapTimer);
    };
  }, [recommendReveal]);

  // Intercept triple-click at mousedown phase to prevent browser from
  // extending paragraph selection across sibling message boundaries.
  // preventDefault() stops the default selection, then we manually select
  // only the clicked block-level element's contents.
  const handleTripleClickDown = React.useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.detail < 3) return;
    e.preventDefault();
    const target = e.target as HTMLElement;
    const block = target.closest("p, li, h1, h2, h3, h4, h5, h6, pre, blockquote, td, th");
    const container = block && e.currentTarget.contains(block) ? block : e.currentTarget;
    const sel = window.getSelection();
    if (sel) {
      const range = document.createRange();
      range.selectNodeContents(container);
      sel.removeAllRanges();
      sel.addRange(range);
    }
  }, []);

  const List = React.useMemo(() => {
    const Comp = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
      ({ className, ...props }, ref) => (
        <div
          ref={ref}
          className={cn("mx-auto max-w-[1040px] space-y-7 px-6 pb-3 pt-8 md:px-10 lg:pt-10", className)}
          {...props}
        />
      )
    );
    Comp.displayName = "MessageList";
    return Comp;
  }, []);

  const Footer = React.useMemo(() => {
    const Comp = () => <div aria-hidden="true" className="h-8" />;
    Comp.displayName = "MessageListFooter";
    return Comp;
  }, []);

  if (messages.length === 0) {
    if (isLoading) {
      return <div className="h-full" />;
    }
    return <WelcomeScreen />;
  }

  return (
    <div className="relative h-full">
      <Virtuoso
        key={sessionKey ?? "empty"}
        ref={virtuosoRef}
        data={messages}
        initialTopMostItemIndex={initialTopMostItemIndex}
        // 原生平滑跟随：仅当用户位于底部时，内容增长（token/timeline）由 Virtuoso 平滑推入视口，
        // 避免手动赋值与内部布局互相拉扯导致的闪动；用户滚离后 isAtBottom=false 不再跟随。
        // 会话加载贴底由布局 effect 负责；发送/完成贴底由 streaming effect 负责。
        followOutput={(isAtBottom) => (isAtBottom ? "smooth" : false)}
        scrollerRef={(node) => {
          scrollerRef.current = node as HTMLElement | null;
          if (node && !node.dataset.scrollListenerAttached) {
            node.dataset.scrollListenerAttached = "1";
            node.addEventListener("scroll", handleScrollerScrollRef.current!, {
              passive: true
            });
          }
        }}
        rangeChanged={handleRangeChanged}
        className="h-full"
        components={{ List, Footer }}
        itemContent={(index, message) => (
          <div
            data-message-id={message.id}
            className={cn(index === messages.length - 1 && "animate-fade-up")}
            onMouseDown={handleTripleClickDown}
          >
            <MessageItem message={message} />
          </div>
        )}
      />
      <QuestionRail
        items={userQuestions}
        activeId={activeQuestionId}
        onSelect={handleSelectQuestion}
      />
      {showScrollDown ? (
        <button
          type="button"
          aria-label="滚动到底部"
          onClick={() => scrollToBottom()}
          className="absolute bottom-4 right-5 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-soft transition hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
