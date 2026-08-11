import * as React from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { ArrowDown } from "lucide-react";

import { ChatTurnItem } from "@/components/chat/ChatTurnItem";
import { ConversationMinimap } from "@/components/chat/ConversationMinimap";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";
import type { Message } from "@/types";
import { groupMessagesIntoTurns } from "@/utils/chatTurns";

/** 距底部超过该距离（px）视为用户真实滚离，暂停自动跟随 */
const DETACH_GAP = 40;

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  /**
   * 遗留接口：滚动由 Virtuoso followOutput 单一权威负责，
   * 本组件不再消费该值（保留在 props 中仅为兼容调用方，禁止在组件内使用）。
   */
  isStreaming: boolean;
  sessionKey?: string | null;
}

export function MessageList({ messages, isLoading, sessionKey }: MessageListProps) {
  const virtuosoRef = React.useRef<VirtuosoHandle | null>(null);
  const scrollerRef = React.useRef<HTMLElement | null>(null);
  const recommendReveal = useChatStore((state) => state.recommendReveal);
  const initialTopMostItemIndex = React.useMemo(
    () => ({ index: "LAST" as const, align: "end" as const }),
    []
  );

  // 稳定 viewKey：只有「已存在的会话 id → 另一个会话 id」（用户切换历史会话）时才更新。
  // null→UUID（新会话首答落库）与初次加载（null→id）都不重建 Virtuoso，
  // 避免「Timeline 完成、正文开始输出」的瞬间整树 remount 造成跳动。
  const [virtuosoKey, setVirtuosoKey] = React.useState<string>(() => sessionKey ?? "empty");
  const prevSessionKeyRef = React.useRef<string | null>(sessionKey ?? null);
  React.useEffect(() => {
    const prev = prevSessionKeyRef.current;
    prevSessionKeyRef.current = sessionKey ?? null;
    // 仅「已存在的会话 id → 另一个会话 id」才重建 Virtuoso；
    // null→UUID（新会话首答落库）不重建，避免 Timeline 完成瞬间跳一下
    if (sessionKey && prev && sessionKey !== prev) {
      setVirtuosoKey(sessionKey);
    }
  }, [sessionKey]);

  const turns = React.useMemo(() => groupMessagesIntoTurns(messages), [messages]);

  // 稳定 key：turns 的 key 在 meta 落库时可能从 local-N 变为 turn-M（同一轮）。
  // 按数组位置保持首次出现的 key——位置不变则 key 不变，首答流式全程 DOM 稳定；
  // 会话切换时整个 Virtuoso 随 viewKey 重建，无需清理。
  const stableKeysRef = React.useRef<(string | null)[]>([]);
  const stableTurns = React.useMemo(
    () =>
      turns.map((turn, index) => ({
        ...turn,
        key: stableKeysRef.current[index] ?? (stableKeysRef.current[index] = turn.key)
      })),
    [turns]
  );

  // stableTurns 的 ref 镜像：ResizeObserver / recommendReveal 等回调里读最新值，
  // 避免闭包捕获过期的 length（保证第二、三轮用最新 index）
  const stableTurnsRef = React.useRef(stableTurns);
  stableTurnsRef.current = stableTurns;

  // userDetachedFromBottom：只由真实用户输入（wheel / touchmove / 键盘上翻）置 true；
  // 布局/Timeline 高度变化、Virtuoso 自动调整、程序 scrollToIndex 一律不改。
  const [detached, setDetached] = React.useState(false);
  const [atBottom, setAtBottom] = React.useState(true);
  const detachedRef = React.useRef(false);
  detachedRef.current = detached;

  const isDetachedFromBottom = React.useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return false;
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > DETACH_GAP;
  }, []);

  const isDetachedFromBottomRef = React.useRef(isDetachedFromBottom);
  isDetachedFromBottomRef.current = isDetachedFromBottom;

  // 输入监听：只登记 wheel / touch / keydown 等真实输入路径；普通 scroll 事件
  // （程序滚动、布局变化都会触发）不用于推断「用户滚离」。处理器只依赖 ref 与
  // 稳定的 setState，一次性创建后跨渲染复用。监听挂在 scroller 上（dataset 去重，
  // Virtuoso 随 viewKey 重建时新节点会重新挂载）。
  const handleUserInputRef = React.useRef<((event: Event) => void) | null>(null);
  if (handleUserInputRef.current === null) {
    handleUserInputRef.current = (event: Event) => {
      if (event.type === "keydown") {
        const e = event as KeyboardEvent;
        const pageUp = e.key === "PageUp";
        const home = e.key === "Home";
        const arrowUp = e.key === "ArrowUp";
        const shiftSpace = e.key === " " && e.shiftKey;
        if (!(pageUp || home || arrowUp || shiftSpace)) return;
      } else if (event.type === "touchstart") {
        // 轻点不算滚离，位置判断以 touchmove 为准
        return;
      } else if (event.type === "wheel") {
        // passive wheel 在滚动应用前触发，位置判断读到的是滚动前的位置：
        // 明确上翻（deltaY < 0）即视为用户向上浏览；下翻仍按位置判断
        if ((event as WheelEvent).deltaY < 0) {
          detachedRef.current = true;
          setDetached(true);
          return;
        }
      } else if (event.type !== "touchmove") {
        return;
      }
      if (isDetachedFromBottomRef.current()) {
        detachedRef.current = true;
        setDetached(true);
      }
    };
  }

  const attachScroller = React.useCallback((node: HTMLElement | null) => {
    scrollerRef.current = node;
    if (node && !node.dataset.userInputAttached) {
      node.dataset.userInputAttached = "1";
      node.addEventListener("wheel", handleUserInputRef.current!, { passive: true });
      node.addEventListener("touchstart", handleUserInputRef.current!, { passive: true });
      node.addEventListener("touchmove", handleUserInputRef.current!, { passive: true });
      node.addEventListener("keydown", handleUserInputRef.current!);
      // 阅读线检测的滚动监听（rAF 合并 + 程序滚动锁定）
      node.addEventListener("scroll", handleScrollRef.current!, { passive: true });
    }
  }, []);

  // Virtuoso 是唯一滚动权威。业务判断不再是「是否数学意义上的底部」，
  // 而是「用户有没有主动离开最新消息」：detached=false 就跟随
  // （含 ResizeObserver scrollToIndex 与内容增长），detached=true 停止。
  // （签名仍兼容 Virtuoso 的 (isAtBottom) => FollowOutputScalarType，参数省略。）
  // 最新 Turn 自身高度增长（turns 数不变）由 Latest Turn ResizeObserver
  // → scrollToIndex(last, end) 兜底（见下方 effect），两者共用 detached 语义。
  // detached 用 ref 同步，避免闭包过期；程序滚动/布局变化不影响 detached。
  const followOutput = React.useCallback(() => {
    return detachedRef.current ? false : "auto";
  }, []);

  const handleAtBottomChange = React.useCallback((isAtBottom: boolean) => {
    setAtBottom(isAtBottom);
    // 回到底部即重新附着（该回调由真实滚动驱动）；
    // ref 同步要与 setState 同时完成，避免 ResizeObserver 回调读到过期 true
    if (isAtBottom) {
      detachedRef.current = false;
      setDetached(false);
    }
  }, []);

  // 当前阅读轮次：由「视口阅读线」判定（视口顶部向下 35% 处）。
  // 命中算法而非最近距离——阅读线穿过哪一轮就是哪一轮；
  // 线刚好落在两轮 gap 之间时取上方最近一轮，绝不提前跳到下一轮。
  // null = 布局未完成/会话刚切换，不显示任何高亮（避免错误闪一下）。
  // 虚拟化列表只有可见项在 DOM，而阅读线必然落在可见区域内，
  // 因此直接量 [data-turn-index] 元素的 rect 即可，无需全量数据。
  const [activeTurnIndex, setActiveTurnIndex] = React.useState<number | null>(null);

  const updateActiveTurn = React.useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const scrollerRect = scroller.getBoundingClientRect();
    // 未布局（高度 0）时无法判定阅读线：保持 null，避免误判
    if (scrollerRect.height <= 0) return;
    const readY = scrollerRect.top + scrollerRect.height * 0.35;
    const elements = Array.from(scroller.querySelectorAll<HTMLElement>("[data-turn-index]"));
    if (elements.length === 0) return;

    // 1. 优先找真正被阅读线穿过的 Turn
    const hit = elements.find((el) => {
      const rect = el.getBoundingClientRect();
      return rect.top <= readY && rect.bottom > readY;
    });
    if (hit) {
      const index = Number(hit.dataset.turnIndex);
      if (Number.isFinite(index)) setActiveTurnIndex(index);
      return;
    }
    // 2. 阅读线刚好落在 Turn 间距中：取上方最近的一轮
    let previous: HTMLElement | null = null;
    for (const el of elements) {
      const rect = el.getBoundingClientRect();
      if (rect.top <= readY) previous = el;
      else break;
    }
    if (previous) {
      const index = Number(previous.dataset.turnIndex);
      if (Number.isFinite(index)) setActiveTurnIndex(index);
    }
  }, []);

  // scroll 监听只做一件事：rAF 合并后按阅读线更新 active（每帧最多一次）
  const activeFrameRef = React.useRef<number | null>(null);
  const handleNavigationScroll = React.useCallback(() => {
    if (activeFrameRef.current !== null) return;
    activeFrameRef.current = requestAnimationFrame(() => {
      activeFrameRef.current = null;
      updateActiveTurn();
    });
  }, [updateActiveTurn]);

  const handleScrollRef = React.useRef<((event: Event) => void) | null>(null);
  if (handleScrollRef.current === null) {
    handleScrollRef.current = () => {
      handleNavigationScroll();
    };
  }

  // 新消息发送（turns 数量增长且新 turn 含 user）：重置滚离标记并立即贴底一次，
  // 只执行一次、无任何 timer；此后的内容增长由 followOutput 与
  // Latest Turn ResizeObserver → scrollToIndex 接管。
  // 历史加载贴底仅依赖 initialTopMostItemIndex LAST（Virtuoso 在 messages 非空时才挂载）。
  const prevTurnsCountRef = React.useRef(stableTurns.length);
  React.useEffect(() => {
    const prevCount = prevTurnsCountRef.current;
    prevTurnsCountRef.current = stableTurns.length;
    if (stableTurns.length > prevCount && stableTurns[stableTurns.length - 1]?.user) {
      // 先同步 ref 再滚动：detachedRef 只靠 render 后同步会晚一拍——新 Turn 发出时
      // ref 可能仍是上一轮的 true，首个 ResizeObserver 回调被跳过，第二轮从一开始失去跟随
      const detachedBefore = detachedRef.current;
      detachedRef.current = false;
      setDetached(false);
      const latestIndex = stableTurns.length - 1;
      if (import.meta.env.DEV) {
        console.debug("[scroll]", {
          reason: "new-turn",
          detachedBefore,
          detachedAfter: false,
          latestIndex
        });
      }
      virtuosoRef.current?.scrollToIndex({ index: latestIndex, align: "end", behavior: "auto" });
    }
  }, [stableTurns.length]);

  // ---- Latest Turn ResizeObserver → scrollToIndex ----
  // 第二、三轮起，最新 Turn 的 Timeline/正文/Thinking/Sources 持续增长只改变
  // 「最后一个 ChatTurn 自身高度」，turns.length 与数据项不变：Virtuoso 的
  // followOutput 只对数据/条目数变化生效，感知不到单条目纯高度增长，
  // 页面会停在回答上半部分。方案：观察最新 Turn 外层容器，尺寸变化经 rAF
  // 合并后 scrollToIndex(last, align: "end")（Virtuoso 仍是唯一滚动权威）。
  // detached 时跳过，用户回到底部后自动恢复跟随。
  const [latestTurnEl, setLatestTurnEl] = React.useState<HTMLDivElement | null>(null);
  const handleLatestTurnRef = React.useCallback((el: HTMLDivElement | null) => {
    setLatestTurnEl(el);
  }, []);
  React.useEffect(() => {
    if (!latestTurnEl) return;
    // frame-level merge：同一帧内多次 resize 只触发一次 scrollToIndex
    let pendingFrame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (detachedRef.current) return;
      if (pendingFrame !== null) return;
      pendingFrame = requestAnimationFrame(() => {
        pendingFrame = null;
        const latestIndex = stableTurnsRef.current.length - 1;
        if (latestIndex < 0 || detachedRef.current) return;
        if (import.meta.env.DEV) {
          console.debug("[scroll]", {
            reason: "latest-turn-resize",
            detached: detachedRef.current,
            latestIndex,
            action: "scrollToIndex"
          });
        }
        virtuosoRef.current?.scrollToIndex({
          index: latestIndex,
          align: "end",
          behavior: "auto"
        });
      });
    });
    observer.observe(latestTurnEl);
    return () => {
      observer.disconnect();
      if (pendingFrame !== null) {
        cancelAnimationFrame(pendingFrame);
        pendingFrame = null;
      }
    };
  }, [latestTurnEl, stableTurns.length]);

  const scrollToLatest = React.useCallback(() => {
    // 先同步 ref 再滚动：点击后紧接着的 ResizeObserver 回调必须看到 false（不等 render）
    detachedRef.current = false;
    setDetached(false);
    virtuosoRef.current?.scrollToIndex({
      index: stableTurns.length - 1,
      align: "end",
      behavior: "smooth"
    });
  }, [stableTurns.length]);

  // Minimap 导航是显式用户动作：置 detached=true（绝不与 AI 自动跟随抢占滚动，
  // 语义同 wheel/键盘输入），随后由 Virtuoso 执行平滑滚动。
  // 不主动设置 active——高亮跟随真实滚动自然经过各轮，最后停在目标轮。
  const handleMinimapNavigate = React.useCallback((index: number) => {
    detachedRef.current = true;
    setDetached(true);
    virtuosoRef.current?.scrollToIndex({ index, align: "start", behavior: "smooth" });
  }, []);

  // 会话切换（virtuosoKey 变化）时重置 active：DOM 尚未布局，任何旧值都会闪错。
  // 布局完成后再经 rAF 由阅读线计算真实 active（Test：切换后绝不能继承上一会话）。
  React.useEffect(() => {
    setActiveTurnIndex(null);
  }, [virtuosoKey]);

  // 布局完成后（virtuosoKey / 轮次变化）补一次阅读线计算——无滚动事件也能校准
  React.useEffect(() => {
    const frame = requestAnimationFrame(() => {
      updateActiveTurn();
    });
    return () => cancelAnimationFrame(frame);
  }, [virtuosoKey, stableTurns.length, updateActiveTurn]);

  // List 容器不得使用 margin（space-y-*）：margin 会破坏 Virtuoso 的 item 测量，
  // 导致滚到底/跳动。Turn 间距由 ChatTurnItem 内部的 item padding（pb-7）承担，
  // 底部呼吸空间由最后 item 的 pb-8 承担（不再用本容器 padding——pb-8 不属于
  // 任何 item 的可测量高度，会让 scrollToIndex(align: "end") 与真底存在偏差）。
  const List = React.useMemo(() => {
    const Comp = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
      ({ className, ...props }, ref) => (
        <div
          ref={ref}
          className={cn("mx-auto max-w-[960px] px-4 pt-4 sm:px-6 lg:pt-5", className)}
          {...props}
        />
      )
    );
    Comp.displayName = "MessageList";
    return Comp;
  }, []);

  // 无 Footer：底部呼吸空间由最后 item 的 padding（pb-8）承担，属于 item 可测量高度，
  // 这样 scrollToIndex(last, align: "end") 对齐的就是真正的列表底，
  // 不再被 h-8 占位或容器 padding 架空导致「刚滚到最新但 atBottom=false」。

  // 推荐面板展开是用户主动动作：滚到该 turn 可见即可，交由 Virtuoso 的
  // scrollIntoView 依据其自身尺寸缓存计算对齐（Virtuoso 是唯一滚动权威）。
  // 不再直接量 DOM 几何、不再触碰 scroller.scrollTop/scrollTo，也不用
  // 100/420ms 的 setTimeout 补滚。触发时机仍由 store 的 recommendReveal 控制
  // （loading/ready/error 各置一次新对象即重新触发）；stableTurns 只经 ref 读取，
  // 避免内容流式增长时该 effect 因 turns 变化而重复滚动。
  React.useEffect(() => {
    if (!recommendReveal) return;
    const revealId = recommendReveal.id;
    const turnIndex = stableTurnsRef.current.findIndex(
      (t) => t.user?.id === revealId || t.assistant?.id === revealId
    );
    if (turnIndex === -1) return;
    virtuosoRef.current?.scrollIntoView({ index: turnIndex, behavior: "smooth", align: "end" });
  }, [recommendReveal]);

  if (messages.length === 0) {
    if (isLoading) {
      return <div className="h-full" />;
    }
    return <WelcomeScreen />;
  }

  return (
    <div className="relative h-full">
      <Virtuoso
        key={virtuosoKey}
        ref={virtuosoRef}
        data={stableTurns}
        initialTopMostItemIndex={initialTopMostItemIndex}
        followOutput={followOutput}
        atBottomStateChange={handleAtBottomChange}
        scrollerRef={attachScroller}
        className="h-full"
        components={{ List }}
        itemContent={(index, turn) => (
          // 外层 div 提供阅读线锚点（data-turn-index）：虚拟化下仅可见项在 DOM，
          // 阅读线（视口 30%）必然落在可见区域内，直接量 rect 即可判定当前轮
          <div data-turn-index={index}>
            <ChatTurnItem
              turn={turn}
              isLatestTurn={index === stableTurns.length - 1}
              // Turn 间距用 item padding（pb-7）而非 List 的 margin（space-y-*），
              // 保证 Virtuoso item 测量准确（margin 会破坏测量导致滚到底/跳动）；
              // 最后 item 多给 pb-8 作为底部呼吸空间（属于 item 可测量高度，
              // scrollToIndex align: "end" 与真底一致）
              className={index === stableTurns.length - 1 ? "pb-8" : "pb-7"}
              // 仅最新一轮挂 ref（Latest Turn ResizeObserver 观察目标），其余不传避免误绑定
              onRef={index === stableTurns.length - 1 ? handleLatestTurnRef : undefined}
            />
          </div>
        )}
      />
      {/* 对话导航刻度：≥4 轮时显示，桌面端（lg）渲染；垂直居中于阅读列右缘
          （右侧 16-24px），实际高度由「轮次数 × 每根线高」决定——一小段刻度，
          不贯穿整页；导航是显式用户动作，点击置 detached 后由 Virtuoso 平滑滚动 */}
      {stableTurns.length >= 4 ? (
        <div className="pointer-events-none absolute top-1/2 right-[max(1.5rem,calc(50%_-_464px))] z-10 hidden -translate-y-1/2 lg:block">
          <div className="pointer-events-auto">
            <ConversationMinimap
              turns={stableTurns}
              activeIndex={activeTurnIndex}
              onNavigate={handleMinimapNavigate}
            />
          </div>
        </div>
      ) : null}
      {detached && !atBottom ? (
        <button
          type="button"
          aria-label="回到底部"
          onClick={scrollToLatest}
          className="absolute bottom-5 right-[max(1.5rem,calc(50%_-_464px))] z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-soft transition hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
