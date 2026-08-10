import * as React from "react";

import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/utils/chatTurns";

/** Minimap 最多渲染的采样槽位数（对话轮数超过时按比例抽样） */
const MAX_SLOTS = 40;
/** Tooltip 摘要最多展示的字符数 */
const SUMMARY_MAX = 30;

interface ConversationMinimapProps {
  turns: ChatTurn[];
  /** 当前可见轮次索引（来自 Virtuoso rangeChanged 的 startIndex） */
  activeIndex: number;
  /** 点击某根线：携带真实 turn 索引（已从采样槽位反算） */
  onNavigate: (index: number) => void;
}

/**
 * 对话导航 rail（GPT 风格）：每轮对话一根线，当前轮加深加宽。
 * 采样：轮数超过 MAX_SLOTS 时按比例抽取槽位，点击时反算回真实索引，
 * 保证「最后一条」永远对应最后一个槽位、导航语义不漂移。
 * 纯展示组件，不做任何滚动——滚动由父组件（唯一滚动权威 Virtuoso）执行。
 */
export function ConversationMinimap({ turns, activeIndex, onNavigate }: ConversationMinimapProps) {
  const total = turns.length;
  const visible = Math.min(total, MAX_SLOTS);

  const slotToIndex = React.useCallback(
    (slot: number) => (visible <= 1 ? 0 : Math.round((slot / (visible - 1)) * (total - 1))),
    [visible, total]
  );
  const indexToSlot = React.useCallback(
    (index: number) => (total <= 1 ? 0 : Math.round((index / (total - 1)) * (visible - 1))),
    [visible, total]
  );

  const activeSlot = indexToSlot(Math.min(Math.max(activeIndex, 0), total - 1));

  return (
    <nav aria-label="对话导航" className="flex flex-col items-center justify-center gap-1">
      {Array.from({ length: visible }, (_, slot) => {
        const index = slotToIndex(slot);
        const turn = turns[index];
        const isActive = slot === activeSlot;
        const summary = (turn.user?.content ?? turn.assistant?.content ?? "").trim();
        return (
          <button
            key={`${turn.key}-${slot}`}
            type="button"
            aria-label={`跳转到第 ${index + 1} 轮对话`}
            aria-current={isActive ? "true" : undefined}
            onClick={() => onNavigate(index)}
            className="group relative flex h-3.5 w-7 items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
          >
            <span
              className={cn(
                "block rounded-full transition-colors",
                isActive
                  ? "h-[3px] w-6 bg-[var(--merchant-navy)]"
                  : "h-[2px] w-5 bg-slate-300 group-hover:bg-slate-500"
              )}
            />
            {summary ? (
              <span
                role="tooltip"
                className="pointer-events-none absolute right-full top-1/2 z-10 mr-3 hidden max-w-[260px] -translate-y-1/2 truncate rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 shadow-soft group-hover:block"
              >
                <span className="mr-1.5 font-semibold text-slate-800">第 {index + 1} 轮</span>
                {summary.length > SUMMARY_MAX ? `${summary.slice(0, SUMMARY_MAX)}…` : summary}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
