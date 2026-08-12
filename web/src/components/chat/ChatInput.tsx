import * as React from "react";
import { Brain, Lightbulb, Send, Square } from "lucide-react";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";
import { KnowledgeScopeSelector } from "@/components/chat/KnowledgeScopeSelector";

export function ChatInput() {
  const [value, setValue] = React.useState("");
  const [isFocused, setIsFocused] = React.useState(false);
  const isComposingRef = React.useRef(false);
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null);
  // 字段级订阅：流式 token 增量只重渲染依赖它的组件，避免整店无差别刷新
  const sendMessage = useChatStore((state) => state.sendMessage);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const cancelGeneration = useChatStore((state) => state.cancelGeneration);
  const deepThinkingEnabled = useChatStore((state) => state.deepThinkingEnabled);
  const setDeepThinkingEnabled = useChatStore((state) => state.setDeepThinkingEnabled);
  const inputFocusKey = useChatStore((state) => state.inputFocusKey);

  const focusInput = React.useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus({ preventScroll: true });
  }, []);

  const adjustHeight = React.useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 160);
    el.style.height = `${next}px`;
  }, []);

  React.useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  React.useEffect(() => {
    if (!inputFocusKey) return;
    focusInput();
  }, [inputFocusKey, focusInput]);

  const handleSubmit = async () => {
    if (isStreaming) {
      cancelGeneration();
      focusInput();
      return;
    }
    if (!value.trim()) return;
    const next = value;
    setValue("");
    focusInput();
    await sendMessage(next);
    focusInput();
  };

  const hasContent = value.trim().length > 0;

  return (
    <div className="space-y-2">
      <div
        className={cn(
          "relative flex min-w-0 flex-col rounded-xl border bg-white px-3 pb-2 pt-2.5 shadow-sm transition-all duration-200 sm:px-4",
          isFocused
            ? "border-[var(--merchant-cyan)] shadow-[var(--merchant-shadow-md)]"
            : "border-[var(--merchant-border)] hover:border-[var(--merchant-cyan-border)]"
        )}
      >
        <div className="relative">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={
              deepThinkingEnabled ? "输入需要深入分析的问题..." : "输入商品经营、订单、售后或知识问题..."
            }
            className="max-h-40 min-h-[44px] w-full resize-none border-0 bg-transparent px-1 pb-2 pt-1.5 text-sm leading-6 text-[var(--merchant-text)] shadow-none placeholder:text-[var(--merchant-text-muted)] focus-visible:ring-0 sm:px-2 sm:text-[15px]"
            rows={1}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                const nativeEvent = event.nativeEvent as KeyboardEvent;
                if (
                  nativeEvent.isComposing ||
                  isComposingRef.current ||
                  nativeEvent.keyCode === 229
                ) {
                  return;
                }
                event.preventDefault();
                handleSubmit();
              }
            }}
            aria-label="聊天输入框"
          />
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-[10px] bg-gradient-to-b from-white/0 via-white/40 to-white/90" />
        </div>
        <div className="relative mt-2 flex min-w-0 flex-wrap items-center gap-2 border-t border-[var(--merchant-border)] pt-2">
          <button
            type="button"
            onClick={() => setDeepThinkingEnabled(!deepThinkingEnabled)}
            disabled={isStreaming}
            aria-pressed={deepThinkingEnabled}
            className={cn(
              "rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all",
              deepThinkingEnabled
                ? "border-[var(--merchant-cyan-border)] bg-[var(--merchant-cyan-soft)] text-[var(--merchant-navy)]"
                : "border-[var(--merchant-border)] bg-white text-[var(--merchant-text-muted)] hover:bg-[var(--merchant-surface-subtle)]",
              isStreaming && "cursor-not-allowed opacity-60"
            )}
          >
            <span className="inline-flex items-center gap-2">
              <Brain
                className={cn(
                  "h-3.5 w-3.5",
                  deepThinkingEnabled && "text-[var(--merchant-cyan-strong)]"
                )}
              />
              深度思考
              {deepThinkingEnabled ? (
                <span className="h-2 w-2 rounded-full bg-[var(--merchant-cyan)] animate-pulse" />
              ) : null}
            </span>
          </button>
          <div className="min-w-0 max-w-full">
            <KnowledgeScopeSelector />
          </div>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!hasContent && !isStreaming}
            aria-label={isStreaming ? "停止生成" : "发送消息"}
            className={cn(
              "ml-auto rounded-full p-2.5 transition-all duration-200",
              isStreaming
                ? "bg-orange-100 text-[var(--merchant-alert)] hover:bg-orange-200"
                : hasContent
                  ? "bg-[var(--merchant-navy)] text-white hover:bg-[#0d3b5d]"
                  : "cursor-not-allowed bg-slate-100 text-slate-300"
            )}
          >
            {isStreaming ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
      {deepThinkingEnabled ? (
        <p className="text-xs text-[var(--merchant-cyan-strong)]">
          <span className="inline-flex items-center gap-1.5">
            <Lightbulb className="h-3.5 w-3.5" />
            深度思考已开启，将更细致地核对规则边界
          </span>
        </p>
      ) : null}
    </div>
  );
}
