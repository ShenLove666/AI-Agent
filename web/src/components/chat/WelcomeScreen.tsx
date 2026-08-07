import * as React from "react";
import { Brain, CalendarRange, PackageX, Send, Square, Wrench } from "lucide-react";

import { KnowledgeScopeSelector } from "@/components/chat/KnowledgeScopeSelector";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";

const MERCHANT_PRESETS = [
  {
    title: "质量问题退款",
    description: "核对质检不合格后的退款与运费责任",
    prompt: "商品经质检确认存在质量问题，商家应如何处理退款和退货运费？",
    icon: PackageX
  },
  {
    title: "七天退货边界",
    description: "判断已拆封商品是否适用七天无理由",
    prompt: "数码商品已拆封并激活，是否还适用七天无理由退货？请说明判断边界。",
    icon: CalendarRange
  },
  {
    title: "保修期内维修",
    description: "梳理报修材料、寄修流程与处理时限",
    prompt: "顾客反馈商品在保修期内故障，请给出需要收集的材料和维修处理流程。",
    icon: Wrench
  }
] as const;

export function WelcomeScreen() {
  const [value, setValue] = React.useState("");
  const [isFocused, setIsFocused] = React.useState(false);
  const isComposingRef = React.useRef(false);
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);
  const { sendMessage, isStreaming, cancelGeneration, deepThinkingEnabled, setDeepThinkingEnabled } =
    useChatStore();

  const focusInput = React.useCallback(() => textareaRef.current?.focus({ preventScroll: true }), []);

  React.useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`;
  }, [value]);

  const handleSubmit = async () => {
    if (isStreaming) {
      cancelGeneration();
      focusInput();
      return;
    }
    if (!value.trim()) return;
    const next = value;
    setValue("");
    await sendMessage(next);
    focusInput();
  };

  const hasContent = value.trim().length > 0;

  return (
    <div className="flex min-h-full w-full items-start justify-center overflow-y-auto bg-[var(--merchant-surface-subtle)] px-3 py-6 sm:px-6 sm:py-10">
      <div className="w-full max-w-[900px]">
        <div className="flex flex-col gap-5 border-b border-[var(--merchant-border)] pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--merchant-cyan-strong)]">
              Merchant after-sales assistant
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--merchant-navy)] sm:text-3xl">
              今天要处理哪类售后问题？
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--merchant-text-muted)]">
              结合商家规则与知识资料，快速核对退款、退货和保修边界。
            </p>
          </div>
          <div className="flex flex-wrap gap-2" aria-label="当前模型配置">
            <span className="rounded-full border border-[var(--merchant-border)] bg-white px-3 py-1.5 text-xs text-[var(--merchant-text-muted)]">
              本地模型配置 · <strong className="text-[var(--merchant-navy)]">V4 Flash</strong>
            </span>
            <span className="rounded-full border border-[var(--merchant-border)] bg-white px-3 py-1.5 text-xs text-[var(--merchant-text-muted)]">
              向量规格 · <strong className="text-[var(--merchant-navy)]">BGE 512d</strong>
            </span>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {MERCHANT_PRESETS.map((preset) => {
            const Icon = preset.icon;
            return (
              <button
                key={preset.title}
                type="button"
                onClick={() => {
                  if (isStreaming) return;
                  setValue(preset.prompt);
                  focusInput();
                }}
                disabled={isStreaming}
                className="group min-w-0 rounded-[var(--merchant-radius-md)] border border-[var(--merchant-border)] bg-white p-4 text-left shadow-[var(--merchant-shadow-sm)] transition-colors hover:border-[var(--merchant-cyan-border)] hover:bg-[var(--merchant-cyan-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--merchant-focus)] disabled:opacity-60"
              >
                <Icon className="h-5 w-5 text-[var(--merchant-alert)]" />
                <p className="mt-4 text-sm font-semibold text-[var(--merchant-navy)]">{preset.title}</p>
                <p className="mt-1 text-xs leading-5 text-[var(--merchant-text-muted)]">{preset.description}</p>
              </button>
            );
          })}
        </div>

        <div className="mt-5 rounded-[var(--merchant-radius-lg)] border border-[var(--merchant-border)] bg-white p-3 shadow-[var(--merchant-shadow-md)] sm:p-4">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={deepThinkingEnabled ? "描述需要深入核对的售后场景..." : "输入订单场景、商品状态或顾客诉求..."}
            className="max-h-36 min-h-[72px] w-full resize-none border-0 bg-transparent px-1 py-1 text-sm leading-6 text-[var(--merchant-text)] placeholder:text-[var(--merchant-text-muted)] focus:outline-none sm:text-[15px]"
            rows={2}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            onCompositionStart={() => { isComposingRef.current = true; }}
            onCompositionEnd={() => { isComposingRef.current = false; }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.shiftKey) return;
              const nativeEvent = event.nativeEvent as KeyboardEvent;
              if (nativeEvent.isComposing || isComposingRef.current || nativeEvent.keyCode === 229) return;
              event.preventDefault();
              handleSubmit();
            }}
            aria-label="发送消息"
          />
          <div className={cn("mt-2 flex flex-wrap items-center gap-2 border-t pt-3", isFocused ? "border-[var(--merchant-cyan-border)]" : "border-[var(--merchant-border)]")}>
            <button
              type="button"
              onClick={() => setDeepThinkingEnabled(!deepThinkingEnabled)}
              disabled={isStreaming}
              aria-pressed={deepThinkingEnabled}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-xs font-medium",
                deepThinkingEnabled
                  ? "border-[var(--merchant-cyan-border)] bg-[var(--merchant-cyan-soft)] text-[var(--merchant-navy)]"
                  : "border-[var(--merchant-border)] text-[var(--merchant-text-muted)]"
              )}
            >
              <Brain className="h-3.5 w-3.5" />
              深度思考
            </button>
            <div className="min-w-0 max-w-full"><KnowledgeScopeSelector /></div>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!hasContent && !isStreaming}
              aria-label={isStreaming ? "停止生成" : "发送消息"}
              className={cn(
                "ml-auto inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
                isStreaming
                  ? "bg-orange-100 text-[var(--merchant-alert)]"
                  : hasContent
                    ? "bg-[var(--merchant-navy)] text-white hover:bg-[#0d3b5d]"
                    : "cursor-not-allowed bg-slate-100 text-slate-300"
              )}
            >
              {isStreaming ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <p className="mt-3 text-xs text-[var(--merchant-text-muted)]">
          V4 Flash 与 BGE 512d 为本地配置描述，不代表实时健康检查结果。
        </p>
      </div>
    </div>
  );
}
