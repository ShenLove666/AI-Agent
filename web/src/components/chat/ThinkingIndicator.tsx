import { Brain, Loader2 } from "lucide-react";

interface ThinkingIndicatorProps {
  content?: string;
  duration?: number;
}

/**
 * 深度思考「运行中」状态条。
 * 固定高度（单行），不实时展开完整 reasoning——思考内容会撑开几百 px 的 DOM，
 * 思考一结束又折叠成小条，在虚拟列表里造成一次巨大的高度骤变（位置闪动）。
 * 真实 thinking token 继续进 store，结束后由 MessageItem 的折叠条展示全文，
 * 用户主动点击才展开。
 */
export function ThinkingIndicator({ duration }: ThinkingIndicatorProps) {
  return (
    <div className="rounded-lg border border-[#BFDBFE] bg-[#DBEAFE] px-4 py-3">
      <div className="flex items-center gap-2 text-[#2563EB]">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-sm font-medium">正在深度思考...</span>
        {duration ? (
          <span className="rounded-full bg-[#BFDBFE] px-2 py-0.5 text-xs text-[#2563EB]">
            {duration}秒
          </span>
        ) : null}
        <Brain className="ml-auto h-4 w-4 shrink-0 text-[#2563EB]" />
      </div>
    </div>
  );
}
