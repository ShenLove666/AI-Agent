import * as React from "react";

import { MessageItem } from "@/components/chat/MessageItem";
import type { ChatTurn } from "@/utils/chatTurns";

interface ChatTurnItemProps {
  turn: ChatTurn;
  isLatestTurn: boolean;
  /**
   * 透传到最外层容器（MessageList 传 "pb-7"，最后一轮 "pb-8" 兼作底部呼吸空间）。
   * Turn 间距用 item padding 而非 List 容器上的 margin（space-y-*）：margin 会
   * 破坏 Virtuoso 的 item 测量，导致滚到底/跳动。
   */
  className?: string;
  /**
   * 暴露最外层容器 DOM 节点（Latest Turn ResizeObserver 观察目标）。
   * 由 MessageList 仅对最新一轮传入；挂载时收到节点、卸载时收到 null。
   */
  onRef?: (el: HTMLDivElement | null) => void;
  /**
   * 暴露「用户消息」DOM 节点（minimap 导航的精准定位锚点）。
   * 注意：anchor 只包住 User Message 本身，不是整个 ChatTurn——minimap 的
   * 语义是「这一轮用户说了什么」，导航落点必须是用户问题第一行附近，
   * 而不是整轮（User+Assistant）的中心/开头。
   */
  onUserAnchorRef?: (el: HTMLDivElement | null) => void;
}

/**
 * 一个 Virtuoso Item = 一个完整 Chat Turn（user + assistant）。
 * 内层 div 的 data-message-id 供「推荐面板展开滚入视口」等按消息定位的逻辑使用。
 */
export function ChatTurnItem({
  turn,
  isLatestTurn,
  onRef,
  onUserAnchorRef,
  className
}: ChatTurnItemProps) {
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

  return (
    // 不使用位移动画（animate-fade-up 已删除）：虚拟列表中 item 的位置动画
    // 会与 Virtuoso 的位置计算/尺寸测量冲突，滚动时产生 jump
    <div
      ref={onRef}
      className={className}
      onMouseDown={handleTripleClickDown}
    >
      {turn.user ? (
        <div ref={onUserAnchorRef} data-user-message-anchor data-message-id={turn.user.id}>
          <MessageItem message={turn.user} />
        </div>
      ) : null}
      {turn.assistant ? (
        <div data-message-id={turn.assistant.id}>
          <MessageItem message={turn.assistant} isLatestTurn={isLatestTurn} />
        </div>
      ) : null}
    </div>
  );
}
