import * as React from "react";

import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/utils/chatTurns";

/** 最多渲染的横线条数（超过时按轮次序号均匀采样，首尾保留） */
const MAX_VISIBLE_MARKERS = 36;
/** Tooltip 摘要最多展示的字符数 */
const SUMMARY_MAX = 30;

interface ConversationMinimapProps {
  turns: ChatTurn[];
  /** 当前阅读轮次索引；null = 布局未完成/未知，不显示任何高亮 */
  activeIndex: number | null;
  /** 点击某根线：携带真实 turn 索引（已从采样槽位反算） */
  onNavigate: (index: number) => void;
}

/**
 * 对话导航刻度（GPT 风格）：一轮 User + Assistant = 一根横线。
 * - 所有横线等间距——它代表「对话轮次」而非页面物理高度，
 *   长回答与短回答在导航中各占一根线
 * - 当前轮更深更粗；hover 展开问题摘要 tooltip（不显示轮次编号——
 *   控件目的是快速浏览消息位置，编号对用户没有价值）
 * - 超过 MAX_VISIBLE_MARKERS 轮时按序号均匀采样（首尾槽位对应首尾轮），
 *   active 映射到最近的采样槽位
 * - 纯展示组件，不做任何滚动——滚动由父组件（唯一滚动权威 Virtuoso）执行
 */
export function ConversationMinimap({ turns, activeIndex, onNavigate }: ConversationMinimapProps) {
  const total = turns.length;
  const visible = Math.min(total, MAX_VISIBLE_MARKERS);

  // 槽位 → 真实索引：均匀采样，首尾槽位永远对应首尾轮
  const slotToIndex = React.useCallback(
    (slot: number) => (visible <= 1 ? 0 : Math.round((slot / (visible - 1)) * (total - 1))),
    [visible, total]
  );
  // 真实索引 → 最近槽位（供 active 高亮映射）
  const indexToSlot = React.useCallback(
    (index: number) => (visible <= 1 ? 0 : Math.round((index / (total - 1)) * (visible - 1))),
    [visible, total]
  );

  const activeSlot =
    activeIndex !== null && activeIndex >= 0 && activeIndex < total
      ? indexToSlot(activeIndex)
      : null;

  return (
    <nav aria-label="对话导航" className="flex flex-col items-center gap-0">
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
            className="group relative flex h-[9px] w-8 items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
          >
            {/* active 不突然变长：同宽 w-5，靠颜色 + 粗细表达（更安静） */}
            <span
              className={cn(
                "block rounded-full transition-[height,background-color]",
                isActive
                  ? "h-[3px] w-5 bg-[var(--merchant-navy)]"
                  : "h-[2px] w-5 bg-slate-300 group-hover:bg-slate-500"
              )}
            />
            {summary ? (
              // 只显示问题摘要：不暴露「第 N 轮」编号（aria-label 已承担无障碍语义）
              <span
                role="tooltip"
                className="pointer-events-none absolute right-full top-1/2 z-10 mr-3 hidden max-w-[260px] -translate-y-1/2 truncate rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 shadow-soft group-hover:block"
              >
                {summary.length > SUMMARY_MAX ? `${summary.slice(0, SUMMARY_MAX)}…` : summary}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
