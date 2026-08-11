import * as React from "react";

import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/utils/chatTurns";

/** Tooltip 摘要最多展示的字符数 */
const SUMMARY_MAX = 30;

/** 静态宽度档位：默认全部等长 8px（Codex 式——active 靠颜色+粗细区分，不靠长度） */
const IDLE_WIDTH = 8;
/** hover 中心向邻域衰减扩张：0=hover、1=±1、2=±2、3=±3，更远回落到 8px */
const HOVER_WIDTHS = [30, 24, 18, 13];

function getMarkerWidth(index: number, hoverIndex: number | null): number {
  if (hoverIndex === null) return IDLE_WIDTH;
  return HOVER_WIDTHS[Math.abs(index - hoverIndex)] ?? IDLE_WIDTH;
}

interface ConversationMinimapProps {
  turns: ChatTurn[];
  /** 当前阅读轮次索引；null = 布局未完成/未知，不显示任何高亮 */
  activeIndex: number | null;
  /** 点击某根线：携带真实 turn 索引 */
  onNavigate: (index: number) => void;
}

/**
 * 对话导航 rail（Codex 式 fisheye）：
 * - 一轮 User + Assistant = 一根横线，**全量渲染不采样**——长对话时 rail
 *   自己可滚动（隐藏 scrollbar + overscroll-contain），用户能精确点到每一轮
 * - 长度受 hover 距离控制（hover 中心 ±3 衰减扩张），颜色受 active/hover
 *   状态控制（active 深色 3px 始终 ≥20px；hover 深灰 2px；其余浅灰）
 * - 右端固定：marker 只向左生长（rail 在页面右侧，避免从中心双向扩张的抖动感）
 * - active 变化时 rail 自动滚到对应 marker（直接操作 scrollTop，不用
 *   scrollIntoView——后者可能连带滚动外层容器）；用户正在操作 rail 时不抢位置
 * - tooltip 渲染在 overflow viewport 之外（外层 relative + 绝对定位），不会被裁掉
 * - 纯展示组件，不做聊天区滚动——导航由父组件（唯一滚动权威 Virtuoso）执行
 */
export function ConversationMinimap({ turns, activeIndex, onNavigate }: ConversationMinimapProps) {
  const [hoverIndex, setHoverIndex] = React.useState<number | null>(null);
  const [isInteracting, setIsInteracting] = React.useState(false);
  const [tooltip, setTooltip] = React.useState<{ index: number; y: number } | null>(null);

  const railRef = React.useRef<HTMLDivElement | null>(null);
  const markerRefs = React.useRef(new Map<number, HTMLButtonElement>());

  // active 变化时让 rail 跟随：只滚 rail 自身（scrollTop），不用 scrollIntoView
  // （可能影响外层 ancestor scroll container）；用户正在操作 rail 时让出控制权
  React.useEffect(() => {
    if (activeIndex === null || isInteracting) return;
    const rail = railRef.current;
    const marker = markerRefs.current.get(activeIndex);
    if (!rail || !marker) return;
    const top = marker.offsetTop;
    const bottom = top + marker.offsetHeight;
    const visibleTop = rail.scrollTop;
    const visibleBottom = visibleTop + rail.clientHeight;
    const safe = 32;
    if (top < visibleTop + safe) {
      rail.scrollTop = Math.max(0, top - safe);
    } else if (bottom > visibleBottom - safe) {
      rail.scrollTop = bottom - rail.clientHeight + safe;
    }
  }, [activeIndex, isInteracting]);

  // tooltip 位置按 marker 相对 rail 的 Y 计算（在 overflow viewport 之外渲染）
  const handleMarkerEnter = (index: number, event: React.MouseEvent<HTMLButtonElement>) => {
    setHoverIndex(index);
    const buttonRect = event.currentTarget.getBoundingClientRect();
    const railRect = railRef.current?.getBoundingClientRect();
    if (!railRect) return;
    setTooltip({
      index,
      y: buttonRect.top - railRect.top + buttonRect.height / 2
    });
  };

  const handleMarkerLeave = () => {
    setHoverIndex(null);
    setTooltip(null);
  };

  return (
    <nav
      aria-label="对话导航"
      className="relative"
      onPointerEnter={() => setIsInteracting(true)}
      onPointerLeave={() => {
        setIsInteracting(false);
        setHoverIndex(null);
        setTooltip(null);
      }}
    >
      {/* tooltip 是外层 sibling，不在 overflow viewport 内 → 不会被 rail 裁掉 */}
      {tooltip ? (
        <div
          role="tooltip"
          className="pointer-events-none absolute right-full z-20 mr-3 max-w-[260px] truncate rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 shadow-soft"
          style={{ top: tooltip.y, transform: "translateY(-50%)" }}
        >
          {(() => {
            const turn = turns[tooltip.index];
            const summary = (turn?.user?.content ?? turn?.assistant?.content ?? "").trim();
            return summary.length > SUMMARY_MAX ? `${summary.slice(0, SUMMARY_MAX)}…` : summary;
          })()}
        </div>
      ) : null}

      {/* rail：自己可滚动；隐藏 scrollbar（Firefox scrollbar-width / WebKit ::-webkit-scrollbar）；
          overscroll-contain 防止滚到 rail 边缘后 wheel 穿透到聊天正文 */}
      <div
        ref={railRef}
        className="flex max-h-[min(52vh,420px)] flex-col overflow-y-auto overscroll-contain py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {turns.map((turn, index) => {
          const active = index === activeIndex;
          const hovered = index === hoverIndex;
          const width = getMarkerWidth(index, hoverIndex);
          return (
            <button
              key={turn.key}
              type="button"
              ref={(node) => {
                if (node) markerRefs.current.set(index, node);
                else markerRefs.current.delete(index);
              }}
              aria-label={`跳转到第 ${index + 1} 轮对话`}
              aria-current={active ? "true" : undefined}
              onMouseEnter={(event) => handleMarkerEnter(index, event)}
              onFocus={(event) => handleMarkerEnter(index, event)}
              onMouseLeave={handleMarkerLeave}
              onBlur={handleMarkerLeave}
              onClick={() => onNavigate(index)}
              className="flex h-[9px] w-10 shrink-0 items-center justify-end focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200"
            >
              {/* 右端固定：只向左生长（rail 在页面右侧） */}
              <span
                style={{ width }}
                className={cn(
                  "block rounded-full transition-[width,height,background-color] duration-150 ease-out",
                  active
                    ? "h-[3px] bg-[var(--merchant-navy)]"
                    : hovered
                      ? "h-[2px] bg-slate-600"
                      : "h-[2px] bg-slate-300"
                )}
              />
            </button>
          );
        })}
      </div>
    </nav>
  );
}
