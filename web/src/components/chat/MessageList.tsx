import * as React from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { ArrowDown } from "lucide-react";

import { ChatTurnItem } from "@/components/chat/ChatTurnItem";
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

  // userDetachedFromBottom：只由真实用户输入（wheel / touchmove / 键盘上翻）置 true；
  // 布局/Timeline 高度变化、Virtuoso 自动调整、程序 scrollToIndex 一律不改。
  const [detached, setDetached] = React.useState(false);
  const [atBottom, setAtBottom] = React.useState(true);
  const detachedRef = React.useRef(false);
  detachedRef.current = detached;
  // atBottom 的 ref 镜像：供 ResizeObserver 回调里的 DEV 日志读取最新值
  const atBottomRef = React.useRef(true);
  atBottomRef.current = atBottom;

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
          setDetached(true);
          return;
        }
      } else if (event.type !== "touchmove") {
        return;
      }
      if (isDetachedFromBottomRef.current()) {
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
    }
  }, []);

  // Virtuoso 是唯一滚动权威。业务判断不再是「是否数学意义上的底部」，
  // 而是「用户有没有主动离开最新消息」：detached=false 就跟随
  // （含 ResizeObserver autoscroll 与内容增长），detached=true 停止。
  // （签名仍兼容 Virtuoso 的 (isAtBottom) => FollowOutputScalarType，参数省略。）
  // 最新 Turn 自身高度增长（turns 数不变）由 Latest Turn ResizeObserver
  // → autoscrollToBottom 兜底（见下方 effect），两者共用 detached 语义。
  // detached 用 ref 同步，避免闭包过期；程序滚动/布局变化不影响 detached。
  const followOutput = React.useCallback(() => {
    return detachedRef.current ? false : "auto";
  }, []);

  const handleAtBottomChange = React.useCallback((isAtBottom: boolean) => {
    setAtBottom(isAtBottom);
    // 回到底部即重新附着（该回调由真实滚动驱动）
    if (isAtBottom) setDetached(false);
  }, []);

  // 新消息发送（turns 数量增长且新 turn 含 user）：重置滚离标记并立即贴底一次，
  // 只执行一次、无任何 timer；此后的内容增长由 followOutput 与
  // Latest Turn ResizeObserver → autoscrollToBottom 接管。
  // 历史加载贴底仅依赖 initialTopMostItemIndex LAST（Virtuoso 在 messages 非空时才挂载）。
  const prevTurnsCountRef = React.useRef(stableTurns.length);
  React.useEffect(() => {
    const prevCount = prevTurnsCountRef.current;
    prevTurnsCountRef.current = stableTurns.length;
    if (stableTurns.length > prevCount && stableTurns[stableTurns.length - 1]?.user) {
      setDetached(false);
      virtuosoRef.current?.scrollToIndex({ index: stableTurns.length - 1, align: "end" });
    }
  }, [stableTurns.length]);

  // ---- Latest Turn ResizeObserver → autoscrollToBottom ----
  // 第二、三轮起，最新 Turn 的 Timeline/正文/Thinking/Sources 持续增长只改变
  // 「最后一个 ChatTurn 自身高度」，turns.length 与数据项不变：Virtuoso 的
  // followOutput 只对数据/条目数变化生效，感知不到单条目纯高度增长，
  // 页面会停在回答上半部分。方案：观察最新 Turn 外层容器，尺寸变化经 rAF
  // 合并后调用 autoscrollToBottom（Virtuoso 仍是唯一滚动权威）。
  // detached 时跳过，用户回到底部后自动恢复跟随。
  const [latestTurnEl, setLatestTurnEl] = React.useState<HTMLDivElement | null>(null);
  const handleLatestTurnRef = React.useCallback((el: HTMLDivElement | null) => {
    setLatestTurnEl(el);
  }, []);
  React.useEffect(() => {
    if (!latestTurnEl) return;
    // frame-level merge：同一帧内多次 resize 只触发一次 autoscrollToBottom
    let pendingFrame: number | null = null;
    const observer = new ResizeObserver(() => {
      if (detachedRef.current) return;
      if (pendingFrame !== null) return;
      if (import.meta.env.DEV) {
        console.debug("[scroll]", {
          latestTurnResize: true,
          detached: detachedRef.current,
          atBottom: atBottomRef.current,
          autoscrollTriggered: true
        });
      }
      pendingFrame = requestAnimationFrame(() => {
        pendingFrame = null;
        virtuosoRef.current?.autoscrollToBottom();
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
    virtuosoRef.current?.scrollToIndex({
      index: stableTurns.length - 1,
      align: "end",
      behavior: "smooth"
    });
    setDetached(false);
  }, [stableTurns.length]);

  // List 容器不得使用 margin（space-y-*）：margin 会破坏 Virtuoso 的 item 测量，
  // 导致滚到底/跳动。Turn 间距改由 ChatTurnItem 内部的 item padding（pb-7）承担，
  // 底部呼吸空间由本容器的 pb-8 承担（原 h-8 Footer 已删除，见下）。
  const List = React.useMemo(() => {
    const Comp = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
      ({ className, ...props }, ref) => (
        <div
          ref={ref}
          className={cn("mx-auto max-w-[960px] px-4 pb-8 pt-8 sm:px-6 lg:pt-10", className)}
          {...props}
        />
      )
    );
    Comp.displayName = "MessageList";
    return Comp;
  }, []);

  // 无 Footer：底部呼吸空间由 List 容器 padding（pb-8）承担。
  // 这样 scrollToIndex(last, align: "end") 对齐的就是真正的列表底，
  // 不再被 h-8 占位架空导致「刚滚到最新但 atBottom=false」。

  // 推荐面板展开是用户主动动作：滚到该 turn 可见即可，交由 Virtuoso 的
  // scrollIntoView 依据其自身尺寸缓存计算对齐（Virtuoso 是唯一滚动权威）。
  // 不再直接量 DOM 几何、不再触碰 scroller.scrollTop/scrollTo，也不用
  // 100/420ms 的 setTimeout 补滚。触发时机仍由 store 的 recommendReveal 控制
  // （loading/ready/error 各置一次新对象即重新触发）；stableTurns 只经 ref 读取，
  // 避免内容流式增长时该 effect 因 turns 变化而重复滚动。
  const stableTurnsRef = React.useRef(stableTurns);
  stableTurnsRef.current = stableTurns;
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
          <ChatTurnItem
            turn={turn}
            isLatestTurn={index === stableTurns.length - 1}
            // Turn 间距用 item padding（pb-7）而非 List 的 margin（space-y-*），
            // 保证 Virtuoso item 测量准确（margin 会破坏测量导致滚到底/跳动）
            className="pb-7"
            // 仅最新一轮挂 ref（Latest Turn ResizeObserver 观察目标），其余不传避免误绑定
            onRef={index === stableTurns.length - 1 ? handleLatestTurnRef : undefined}
          />
        )}
      />
      {detached && !atBottom ? (
        <button
          type="button"
          aria-label="回到底部"
          onClick={scrollToLatest}
          className="absolute bottom-5 right-6 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-soft transition hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
