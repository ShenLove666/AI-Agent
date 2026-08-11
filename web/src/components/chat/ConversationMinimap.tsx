import * as React from "react";

import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/utils/chatTurns";

/** Minimap 最多渲染的采样槽位数（对话轮数超过时按比例抽样） */
const MAX_SLOTS = 40;
/** Tooltip 摘要最多展示的字符数 */
const SUMMARY_MAX = 30;

interface ConversationMinimapProps {
  turns: ChatTurn[];
  /** 当前阅读轮次索引（视口阅读线命中，见 MessageList.updateActiveByReadLine） */
  activeIndex: number;
  /** 每轮中心点占总高比例（0-1，真实 DOM 高度）；null 时回退均匀分布 */
  ratios?: number[] | null;
  /** 点击某轮：携带真实 turn 索引（已从采样槽位反算） */
  onNavigate: (index: number) => void;
}

/**
 * 对话导航 rail（GPT 风格）：细轨道 + 圆点。
 * - 平时只保留一条 1px 轨道与圆点，不挡聊天内容；hover 圆点才展开
 *   「第 N 轮 + 摘要」tooltip
 * - 圆点位置按真实 DOM 高度比例（ratios，来自 Virtuoso 已测量高度）：
 *   长回答占更长轨道空间，短回答更短——真正意义上的「地图」；
 *   比例未就绪时均匀分布（首尾槽位仍对应首尾轮）
 * - 纯展示组件，不做任何滚动——滚动由父组件（唯一滚动权威 Virtuoso）执行
 */
export function ConversationMinimap({
  turns,
  activeIndex,
  ratios,
  onNavigate
}: ConversationMinimapProps) {
  const total = turns.length;
  const visible = Math.min(total, MAX_SLOTS);

  // 槽位 → 真实索引：均匀采样，首尾槽位永远对应首尾轮
  const slotToIndex = React.useCallback(
    (slot: number) => (visible <= 1 ? 0 : Math.round((slot / (visible - 1)) * (total - 1))),
    [visible, total]
  );

  // 每轮中心比例：真实高度（ratios）或均匀分布
  const topFor = React.useCallback(
    (index: number) => {
      if (ratios && ratios[index] !== undefined) return ratios[index] * 100;
      return total <= 1 ? 50 : (index / (total - 1)) * 100;
    },
    [ratios, total]
  );

  const slots = React.useMemo(
    () => Array.from({ length: visible }, (_, slot) => slotToIndex(slot)),
    [visible, slotToIndex]
  );

  return (
    <nav aria-label="对话导航" className="relative h-full w-7">
      {/* 细轨道：1px 竖线贯穿，提示「这是整段对话的地图」 */}
      <span
        aria-hidden
        className="absolute inset-y-2 left-1/2 w-px -translate-x-1/2 rounded-full bg-slate-200"
      />
      {slots.map((index) => {
        const turn = turns[index];
        const isActive = index === activeIndex;
        const summary = (turn.user?.content ?? turn.assistant?.content ?? "").trim();
        return (
          <button
            key={`${turn.key}-${index}`}
            type="button"
            aria-label={`跳转到第 ${index + 1} 轮对话`}
            aria-current={isActive ? "true" : undefined}
            onClick={() => onNavigate(index)}
            style={{ top: `${topFor(index)}%` }}
            className="group absolute left-1/2 flex h-3.5 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
          >
            <span
              className={cn(
                "block rounded-full transition-all",
                isActive
                  ? "h-2.5 w-2.5 bg-[var(--merchant-navy)] ring-4 ring-[var(--merchant-cyan-soft)]"
                  : "h-1.5 w-1.5 bg-slate-300 group-hover:scale-125 group-hover:bg-slate-500"
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
