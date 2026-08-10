import * as React from "react";
import { Brain, CalendarRange, PackageX, Send, Square, Wrench } from "lucide-react";

import { KnowledgeScopeSelector } from "@/components/chat/KnowledgeScopeSelector";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";

const MERCHANT_PRESETS = [
  {
    title: "搭配购推荐",
    description: "根据购物篮证据推荐高关联商品",
    prompt: "牛肉适合搭配哪些商品？请给出推荐依据，并说明不能保证实际优惠。",
    icon: PackageX
  },
  {
    title: "即时零售退款",
    description: "核对生鲜与普通商品退款边界",
    prompt: "即时零售订单中的生鲜商品不满意时如何申请退款？请说明判断边界。",
    icon: CalendarRange
  },
  {
    title: "缺货替代规则",
    description: "明确缺货替换与顾客确认流程",
    prompt: "即时零售商品缺货时能否自动替换？请说明需要顾客确认的流程。",
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
              Instant retail AI assistant
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--merchant-navy)] sm:text-3xl">
              今天要处理哪类即时零售问题？
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--merchant-text-muted)]">
              结合经营数据、购物篮洞察与知识库，回答商品经营、订单履约、配送和售后问题。
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
            placeholder={deepThinkingEnabled ? "输入需要深入分析的问题..." : "输入商品经营、订单、售后或知识问题..."}
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
