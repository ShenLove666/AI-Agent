import * as React from "react";

import { MessageItem } from "@/components/chat/MessageItem";
import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/utils/chatTurns";

interface ChatTurnItemProps {
  turn: ChatTurn;
  isLatestTurn: boolean;
  /**
   * 透传到最外层容器（MessageList 传 "pb-7"）。Turn 间距用 item padding
   * 而非 List 容器上的 margin（space-y-*）：margin 会破坏 Virtuoso 的
   * item 测量，导致滚到底/跳动。
   */
  className?: string;
  /**
   * 暴露最外层容器 DOM 节点（Latest Turn ResizeObserver 观察目标）。
   * 由 MessageList 仅对最新一轮传入；挂载时收到节点、卸载时收到 null。
   */
  onRef?: (el: HTMLDivElement | null) => void;
}

/**
 * 一个 Virtuoso Item = 一个完整 Chat Turn（user + assistant）。
 * 内层 div 的 data-message-id 供「推荐面板展开滚入视口」等按消息定位的逻辑使用。
 */
export function ChatTurnItem({ turn, isLatestTurn, onRef, className }: ChatTurnItemProps) {
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
    <div
      ref={onRef}
      className={cn(className, isLatestTurn && "animate-fade-up")}
      onMouseDown={handleTripleClickDown}
    >
      {turn.user ? (
        <div data-message-id={turn.user.id}>
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
