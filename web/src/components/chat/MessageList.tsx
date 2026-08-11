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

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  /**
   * 遗留接口：滚动跟随由本组件内部（新消息 effect + Latest Turn ResizeObserver）
   * 承担，不消费该值（保留在 props 中仅为兼容调用方，禁止在组件内使用）。
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

  // 用户「明确向下滚 + 已接近底部」→ 恢复自动跟随（reattach）。
  // 阈值比 DETACH_GAP 宽：回答还在 streaming 增长时，数学到底很难「追上」，
  // 距底 96px 内即视为用户已回到最新内容区域。只做 detached=false，
  // 不主动 scrollToIndex——下一批 streaming 触发 Latest Turn ResizeObserver 时
  // 看到 detached=false 自然继续跟随，不会突然「吸到底」。
  const REATTACH_GAP = 96;

  const maybeReattachFromUserScroll = React.useCallback(() => {
    if (!detachedRef.current) return;
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const bottomGap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    if (bottomGap <= REATTACH_GAP) {
      detachedRef.current = false;
      setDetached(false);
      if (import.meta.env.DEV) {
        console.debug("[scroll]", {
          reason: "user-returned-near-bottom",
          bottomGap,
          detachedAfter: false
        });
      }
    }
  }, []);
  const maybeReattachRef = React.useRef(maybeReattachFromUserScroll);
  maybeReattachRef.current = maybeReattachFromUserScroll;

  // touch 方向：记录 touchstart 的 Y，touchmove 用位移判断手指方向
  const touchYRef = React.useRef<number | null>(null);

  // ---- 用户显式导航选择（minimap 点击）----
  // minimap 显示 = selectedTurnIndex ?? activeTurnIndex：
  // - activeTurnIndex = viewport 几何事实（阅读线/bottom override）
  // - selectedTurnIndex = 用户显式导航意图（点击刻度）
  // 拆分的原因：点击倒数第二轮时，若目标已在尾部可见、scrollTop 无法再滚，
  // 一帧后几何重算会因 bottom override 把高亮抢回最后一轮——点击看起来「没反应」。
  // selected 一直保持，直到出现真实用户滚动（wheel/touch/keyboard）等明确动作。
  const [selectedTurnIndex, setSelectedTurnIndex] = React.useState<number | null>(null);
  const selectedTurnIndexRef = React.useRef<number | null>(null);
  selectedTurnIndexRef.current = selectedTurnIndex;

  const clearMinimapSelectionRef = React.useRef<() => void>(() => {});
  clearMinimapSelectionRef.current = () => {
    if (selectedTurnIndexRef.current === null) return;
    selectedTurnIndexRef.current = null;
    setSelectedTurnIndex(null);
  };

  // 真实用户滚动后「先更新 active、再释放 selected」：wheel 事件发生时浏览器
  // 还没改 scrollTop，若此刻就清 selected，会先暴露旧的 geometry active
  // （闪一帧旧高亮），滚动完成才更新到新位置。改为在 scroll rAF 中先计算
  // 新的 active，再同一批 React 更新里释放 selected——UI 直接从目标轮跳到新轮。
  const releaseSelectionOnNextScrollRef = React.useRef(false);

  // 取消未完成的 minimap 导航：真实用户滚动意图出现时，pending 的
  // materialize→精准定位 不得再把页面拉回点击目标（用户永远拥有最终控制权）。
  const cancelPendingMinimapNavigation = React.useCallback(() => {
    pendingMinimapIndexRef.current = null;
    minimapNavigatingRef.current = false;
  }, []);

  // 输入监听：只登记 wheel / touch / keydown 等真实输入路径；普通 scroll 事件
  // （程序滚动、布局变化都会触发）不用于推断「用户滚离/滚回」，也不清除
  // minimap 显式选择——只有明确用户输入才能清（与 detached 同一设计原则）。
  // 处理器只依赖 ref 与稳定的 setState，一次性创建后跨渲染复用。
  // 监听挂在 scroller 上（dataset 去重，Virtuoso 随 viewKey 重建时新节点会重新挂载）。
  const handleUserInputRef = React.useRef<((event: Event) => void) | null>(null);
  if (handleUserInputRef.current === null) {
    handleUserInputRef.current = (event: Event) => {
      if (event.type === "keydown") {
        const e = event as KeyboardEvent;
        // 只认滚动键：Tab/Enter/字母等落在 scroller 上的按键不该释放 selected
        const isScrollKey =
          e.key === "PageUp" ||
          e.key === "PageDown" ||
          e.key === "Home" ||
          e.key === "End" ||
          e.key === "ArrowUp" ||
          e.key === "ArrowDown" ||
          e.key === " ";
        if (!isScrollKey) return;
        if (selectedTurnIndexRef.current !== null) {
          releaseSelectionOnNextScrollRef.current = true;
        }
        cancelPendingMinimapNavigation();
        const pageUp = e.key === "PageUp";
        const home = e.key === "Home";
        const arrowUp = e.key === "ArrowUp";
        const shiftSpace = e.key === " " && e.shiftKey;
        // 明确向上浏览 → detached
        if (pageUp || home || arrowUp || shiftSpace) {
          detachedRef.current = true;
          setDetached(true);
          return;
        }
        // End：明确要回最新 → 直接恢复跟随
        if (e.key === "End") {
          detachedRef.current = false;
          setDetached(false);
          return;
        }
        // 其他向下键：等浏览器完成滚动后检查是否接近底部（reattach）
        const pageDown = e.key === "PageDown";
        const arrowDown = e.key === "ArrowDown";
        const space = e.key === " ";
        if ((pageDown || arrowDown || space) && detachedRef.current) {
          requestAnimationFrame(() => {
            maybeReattachRef.current();
          });
        }
        return;
      }

      if (event.type === "touchstart") {
        const touch = (event as TouchEvent).touches[0];
        touchYRef.current = touch?.clientY ?? null;
        return;
      }

      if (event.type === "touchmove") {
        const e = event as TouchEvent;
        const currentY = e.touches[0]?.clientY;
        if (currentY == null || touchYRef.current == null) return;
        const delta = currentY - touchYRef.current;
        touchYRef.current = currentY;
        // 有真实位移的方向滚动 → 标记释放 selected（scroll 后统一执行）
        if (Math.abs(delta) > 3) {
          if (selectedTurnIndexRef.current !== null) {
            releaseSelectionOnNextScrollRef.current = true;
          }
          cancelPendingMinimapNavigation();
        }
        // 触屏方向：手指下滑（delta>0）→ 页面向上 → 浏览历史 → detached
        if (delta > 3) {
          detachedRef.current = true;
          setDetached(true);
          return;
        }
        // 手指上滑（delta<0）→ 页面下滚 → 接近最新 → 尝试 reattach
        if (delta < -3 && detachedRef.current) {
          requestAnimationFrame(() => {
            maybeReattachRef.current();
          });
        }
        return;
      }

      if (event.type === "wheel") {
        const e = event as WheelEvent;
        // 真实用户滚动：标记释放 selected（不立即清——scroll 后先算新 active 再释放）
        if (selectedTurnIndexRef.current !== null) {
          releaseSelectionOnNextScrollRef.current = true;
        }
        cancelPendingMinimapNavigation();
        // passive wheel 在滚动应用前触发（读到滚动前的位置）：
        // 明确上翻即视为向上浏览
        if (e.deltaY < 0) {
          detachedRef.current = true;
          setDetached(true);
          return;
        }
        // 明确下翻且当前 detached：等浏览器完成本帧滚动后再检查 reattach
        if (e.deltaY > 0 && detachedRef.current) {
          requestAnimationFrame(() => {
            maybeReattachRef.current();
          });
        }
        return;
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

  // ---- 滚动跟随只有一个控制器 ----
  // 自动跟随统一由「新消息 effect」与「Latest Turn ResizeObserver → scrollToIndex」
  // 两条显式路径承担（都不再经过 Virtuoso followOutput——避免两套机制
  // 在「用户刚切换到手动浏览」的边界上竞争）。
  // detached=false 才跟随；detached=true（用户意图）时所有程序滚动全部停止。
  // detached 只由用户动作修改：上翻输入 → true；发送新消息/回到底部 → false。

  // atBottom 是几何状态，detached 是用户意图状态——两者互不推导。
  // atBottomStateChange(true) 可能来自程序滚动、内容重测量、streaming 高度变化，
  // 不能据此把 detached 改回 false（否则「用户向上浏览」会被 Virtuoso 的
  // 程序性回调打断，下一批 token 又把页面拉到底，形成上下闪动）。
  // detached 只允许在明确动作处修改：wheel/touch/键盘上翻 → true；
  // 发送新消息、点击「回到底部」→ false。

  // ---- 当前阅读轮次（minimap active）----
  // 统一语义：marker = User Message Anchor。判定模型与 minimap 点击目标一致——
  // 找距视口阅读线（顶部向下 35%）最近的「用户消息锚点」，而不是整个
  // ChatTurn（User+Assistant 盒子）。长 AI 回答不应让同一根线高亮过久；
  // 下一轮用户问题进入屏幕时，active 应自然切到下一根。
  const [activeTurnIndex, setActiveTurnIndex] = React.useState<number | null>(null);
  const activeTurnIndexRef = React.useRef<number | null>(null);
  activeTurnIndexRef.current = activeTurnIndex;

  // 统一 setter：ref 与 state 同步，相同值不重复 set（避免无谓渲染）
  const commitActiveTurn = React.useCallback((index: number) => {
    if (activeTurnIndexRef.current === index) return;
    activeTurnIndexRef.current = index;
    setActiveTurnIndex(index);
  }, []);

  const handleAtBottomChange = React.useCallback((isAtBottom: boolean) => {
    setAtBottom(isAtBottom);
    if (isAtBottom) {
      // 几何到底时高亮最新一轮（阅读语义），但不动 detached
      const latestIndex = stableTurnsRef.current.length - 1;
      if (latestIndex >= 0) commitActiveTurn(latestIndex);
    }
  }, [commitActiveTurn]);

  // ---- updateActiveTurn：User Anchor 最近判定 ----
  // 1) bottom 双阈值 hysteresis：进入底部（≤24px）→ last；已在 last 时须离开
  //    到底部 48px 外才交还 anchor 判定（避免 trackpad 惯性在 23/25/22/26px
  //    间 last/penultimate 来回闪）
  // 2) 其余：35% 阅读线 → 距离最近的 mounted User Anchor（isConnected 过滤）
  // 3) 16px hysteresis：候选与当前距离接近时不切换（临界抖动保护）
  // 4) 小滚动邻接保护：本帧滚动量 < 视口 20% 时最多切 ±1 轮（快速 PageUp/
  //    拖 scrollbar 等大滚动不受限）
  const ACTIVE_READ_LINE_RATIO = 0.35;
  const ACTIVE_SWITCH_HYSTERESIS = 16;
  const BOTTOM_ENTER_GAP = 24;
  const BOTTOM_EXIT_GAP = 48;
  const previousScrollTopRef = React.useRef(0);

  const updateActiveTurn = React.useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const total = stableTurnsRef.current.length;
    if (!total) return;

    // 未布局（高度 0）时无法判定：保持 null，避免误判
    const scrollerRect = scroller.getBoundingClientRect();
    if (scrollerRect.height <= 0) return;

    const bottomGap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    const currentIndex = activeTurnIndexRef.current;

    // 1. bottom override（双阈值 hysteresis）
    if (bottomGap <= BOTTOM_ENTER_GAP) {
      commitActiveTurn(total - 1);
      return;
    }
    if (currentIndex === total - 1 && bottomGap <= BOTTOM_EXIT_GAP) {
      commitActiveTurn(total - 1);
      return;
    }

    // 2. 距阅读线最近的 User Message Anchor
    const readY = scrollerRect.top + scrollerRect.height * ACTIVE_READ_LINE_RATIO;
    let candidateIndex: number | null = null;
    let candidateDistance = Infinity;
    for (const [index, anchor] of userAnchorRefs.current) {
      if (!anchor.isConnected) continue;
      const rect = anchor.getBoundingClientRect();
      const distance = Math.abs(rect.top - readY);
      if (distance < candidateDistance) {
        candidateDistance = distance;
        candidateIndex = index;
      }
    }
    if (candidateIndex === null) return;

    // 3. hysteresis：候选与当前锚点距离接近时不切换
    if (currentIndex !== null && currentIndex !== candidateIndex) {
      const currentAnchor = userAnchorRefs.current.get(currentIndex);
      if (currentAnchor && currentAnchor.isConnected) {
        const currentDistance = Math.abs(currentAnchor.getBoundingClientRect().top - readY);
        if (candidateDistance + ACTIVE_SWITCH_HYSTERESIS >= currentDistance) {
          return;
        }
      }
    }

    // 4. 小滚动邻接保护：本帧滚动量小却算出跨多轮 → 只切 ±1
    const scrollDelta = Math.abs(scroller.scrollTop - previousScrollTopRef.current);
    previousScrollTopRef.current = scroller.scrollTop;
    if (
      currentIndex !== null &&
      Math.abs(candidateIndex - currentIndex) > 1 &&
      scrollDelta < scroller.clientHeight * 0.2
    ) {
      candidateIndex = candidateIndex > currentIndex ? currentIndex + 1 : currentIndex - 1;
    }

    commitActiveTurn(candidateIndex);
  }, [commitActiveTurn]);

  // scroll 监听只做一件事：rAF 合并后按阅读线更新 active（每帧最多一次）。
  // minimap 导航定位期间跳过——定位触发的中间 scroll 位置不代表用户阅读位置。
  // 用户真实滚动后：先算出新的 active，再释放 selected（同一批 React 更新，
  // UI 直接从目标轮跳到新轮，不闪旧 active）。
  const activeFrameRef = React.useRef<number | null>(null);
  const handleNavigationScroll = React.useCallback(() => {
    if (minimapNavigatingRef.current) return;
    if (activeFrameRef.current !== null) return;
    activeFrameRef.current = requestAnimationFrame(() => {
      activeFrameRef.current = null;
      updateActiveTurn();
      if (releaseSelectionOnNextScrollRef.current) {
        releaseSelectionOnNextScrollRef.current = false;
        selectedTurnIndexRef.current = null;
        setSelectedTurnIndex(null);
      }
    });
  }, [updateActiveTurn]);

  const handleScrollRef = React.useRef<((event: Event) => void) | null>(null);
  if (handleScrollRef.current === null) {
    handleScrollRef.current = () => {
      handleNavigationScroll();
    };
  }

  // 新消息发送（turns 数量增长且新 turn 含 user）：重置滚离标记并立即贴底一次，
  // 只执行一次、无任何 timer；此后的内容增长由
  // Latest Turn ResizeObserver → scrollToIndex 接管。
  // 历史加载贴底仅依赖 initialTopMostItemIndex LAST（Virtuoso 在 messages 非空时才挂载）。
  const prevTurnsCountRef = React.useRef(stableTurns.length);
  React.useEffect(() => {
    const prevCount = prevTurnsCountRef.current;
    prevTurnsCountRef.current = stableTurns.length;
    if (stableTurns.length > prevCount && stableTurns[stableTurns.length - 1]?.user) {
      // 发送新问题 → 清除 minimap 显式选择（否则上一轮的选择会一直亮着）
      selectedTurnIndexRef.current = null;
      setSelectedTurnIndex(null);
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

  // ---- Latest Turn ResizeObserver → scrollToIndex（唯一自动跟随控制器）----
  // 最新 Turn 的 Timeline/正文/Thinking/Sources 持续增长只改变「最后一个
  // ChatTurn 自身高度」，turns.length 与数据项不变：Virtuoso 感知不到单条目
  // 纯高度增长，页面会停在回答上半部分。方案：观察最新 Turn 外层容器，
  // 尺寸变化经 rAF 合并后 scrollToIndex(last, align: "end")。
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
    // 回到底部 = 不再看显式选中的历史轮次 → 清除 minimap 显式选择
    selectedTurnIndexRef.current = null;
    setSelectedTurnIndex(null);
    // 先同步 ref 再滚动：点击后紧接着的 ResizeObserver 回调必须看到 false（不等 render）
    detachedRef.current = false;
    setDetached(false);
    virtuosoRef.current?.scrollToIndex({
      index: stableTurns.length - 1,
      align: "end",
      behavior: "smooth"
    });
  }, [stableTurns.length]);

  // ---- Minimap 导航：目标 = User Message Anchor（不是 ChatTurn）----
  // marker 代表「这一轮用户说了什么」，所以定位对象是用户消息锚点：
  // 两级定位——anchor 已 mounted 时直接精确 scrollBy（用户问题落到
  // viewport 顶部 + NAV_TOP_OFFSET）；未 mounted 时 Virtuoso 只负责把该 Turn
  // materialize（align:"start" 只是加载手段，不是最终落点），anchor ref 出现后
  // 立即补一次精确对齐。不再使用 center/end 对齐整个 Turn——Turn 高度由
  // 超长用户输入/Markdown/Timeline/Thinking 决定，「Turn 的中心」没有产品意义。
  const NAV_TOP_OFFSET = 24;
  const userAnchorRefs = React.useRef(new Map<number, HTMLDivElement>());
  const pendingMinimapIndexRef = React.useRef<number | null>(null);

  const scrollUserAnchorIntoPosition = React.useCallback((index: number) => {
    const scroller = scrollerRef.current;
    const anchor = userAnchorRefs.current.get(index);
    if (!scroller || !anchor) return false;
    const scrollerRect = scroller.getBoundingClientRect();
    const anchorRect = anchor.getBoundingClientRect();
    const delta = anchorRect.top - scrollerRect.top - NAV_TOP_OFFSET;
    if (Math.abs(delta) <= 1) return true;
    // Virtuoso 已负责虚拟列表定位；这里只做最后 ~30px 级的精准对齐
    scroller.scrollBy({ top: delta, behavior: "auto" });
    return true;
  }, []);

  // 统一闭合一次 minimap 导航：无论走「已 mounted 精准定位」还是
  // 「materialize → anchor 出现」，最终都回到 pending=null / navigating=false，
  // 并给 geometry active 一个正确基准（selected 仍优先显示，不造成视觉抢占）。
  // 若此处不恢复 navigating=false，后续所有 scroll 的 active 更新会被永久跳过。
  const finishMinimapNavigation = React.useCallback((index: number) => {
    pendingMinimapIndexRef.current = null;
    minimapNavigatingRef.current = false;
    setActiveTurnIndex(index);
  }, []);

  // anchor 挂载回调：存入 Map；若正是 pending 导航目标，等一帧布局稳定后
  // 完成精准定位（远距离点击：Virtuoso materialize → anchor 出现 → 对齐）
  const handleUserAnchorRef = React.useCallback(
    (index: number, node: HTMLDivElement | null) => {
      if (node) {
        userAnchorRefs.current.set(index, node);
      } else {
        userAnchorRefs.current.delete(index);
        return;
      }
      if (pendingMinimapIndexRef.current !== index) return;
      requestAnimationFrame(() => {
        if (pendingMinimapIndexRef.current !== index) return;
        scrollUserAnchorIntoPosition(index);
        finishMinimapNavigation(index);
      });
    },
    [scrollUserAnchorIntoPosition]
  );

  // Minimap 导航是显式用户动作：置 detached=true（绝不与 AI 自动跟随抢占滚动，
  // 语义同 wheel/键盘输入），并记录 selectedTurnIndex（用户显式选择，优先于
  // 几何 active——避免底部 bottom override 把高亮抢回最后一轮）。
  // 导航期间锁定 geometry active 更新：定位触发的中间 scroll 不反复改高亮。
  // selected 一直保持，直到真实用户滚动等明确动作清除。
  const minimapNavigatingRef = React.useRef(false);

  const handleMinimapNavigate = React.useCallback(
    (index: number) => {
      detachedRef.current = true;
      setDetached(true);

      // 用户明确选择了这一轮：立即高亮，不被任何几何回调抢走
      selectedTurnIndexRef.current = index;
      setSelectedTurnIndex(index);

      minimapNavigatingRef.current = true;
      pendingMinimapIndexRef.current = index;

      // Anchor 已在 DOM：不经过 Virtuoso，直接一次精准定位
      if (scrollUserAnchorIntoPosition(index)) {
        finishMinimapNavigation(index);
        return;
      }

      // Anchor 未 mounted：Virtuoso 只负责 materialize，最终落点由
      // handleUserAnchorRef 在 anchor 出现后补齐（align:"start" 不是最终定位）；
      // 若该 Turn 没有 user 消息（无 anchor，如孤立 assistant），本帧后兜底
      // 完成导航（两个 rAF 都检查 pending，先到者生效，不会重复）
      virtuosoRef.current?.scrollToIndex({
        index,
        align: "start",
        behavior: "auto"
      });
      requestAnimationFrame(() => {
        if (pendingMinimapIndexRef.current !== index) return;
        scrollUserAnchorIntoPosition(index);
        finishMinimapNavigation(index);
      });
    },
    [scrollUserAnchorIntoPosition]
  );

  // 会话切换（virtuosoKey 变化）时重置 active 与 minimap 显式选择：
  // DOM 尚未布局，任何旧值都会闪错（Test：切换后绝不能继承上一会话）。
  // 布局完成后再经 rAF 由阅读线计算真实 active。
  React.useEffect(() => {
    setActiveTurnIndex(null);
    selectedTurnIndexRef.current = null;
    setSelectedTurnIndex(null);
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
        // 官方 prop：提升 ResizeObserver 测量性能、减少 streaming 期间的 flickering
        skipAnimationFrameInResizeObserver
        // 顶部预渲染区域：上滚时更早挂载/测量旧 Turn，减少临时 mount 的 layout shift
        increaseViewportBy={{ top: 500, bottom: 200 }}
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
              // 所有轮都挂用户消息锚点（minimap 精准定位目标）
              onUserAnchorRef={(node) => handleUserAnchorRef(index, node)}
            />
          </div>
        )}
      />
      {/* 对话导航刻度：≥4 轮时显示，桌面端（lg）渲染；rail 属于 viewport——
          固定在聊天滚动区最右侧（滚动条内侧），不是正文内容的一部分；
          实际高度由「轮次数 × 每根线高」决定；导航是显式用户动作，
          点击置 detached 后由 Virtuoso 平滑滚动 */}
      {stableTurns.length >= 4 ? (
        <div className="pointer-events-none absolute top-1/2 right-4 z-10 hidden -translate-y-1/2 lg:block">
          <div className="pointer-events-auto">
            <ConversationMinimap
              turns={stableTurns}
              // selected（用户显式导航）优先于几何 active
              activeIndex={selectedTurnIndex ?? activeTurnIndex}
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
          // 「回到底部」属于聊天阅读流，不属于 rail：置于正文底部水平居中，
          // 与右侧刻度彻底分离（rail 跳问题、按钮回最新，视觉上两个独立控件）
          className="absolute bottom-5 left-1/2 z-10 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-soft transition hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
