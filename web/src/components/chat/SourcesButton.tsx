import { FileText } from "lucide-react";

import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chatStore";
import type { SourceRef } from "@/types";

interface SourcesButtonProps {
  messageId: string;
  sources: SourceRef[];
}

/** 来源入口：单个引用图标 + 「N 条依据」计数（不叠多个小图标，降低视觉噪音）。 */
export function SourcesButton({ messageId, sources }: SourcesButtonProps) {
  const openedSourceMessageId = useChatStore((state) => state.openedSourceMessageId);
  const toggleSourcesPanel = useChatStore((state) => state.toggleSourcesPanel);

  if (!sources || sources.length === 0) {
    return null;
  }

  const active = openedSourceMessageId === messageId;

  return (
    <button
      type="button"
      onClick={() => toggleSourcesPanel(messageId)}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full py-1 pl-2 pr-2.5 text-xs transition-colors",
        active
          ? "bg-[#F0F0F1] text-[#1A1A1A]"
          : "text-[#666666] hover:bg-[#F0F0F1] hover:text-[#1A1A1A]"
      )}
    >
      <FileText className="h-3.5 w-3.5 shrink-0" />
      {sources.length} 条依据
    </button>
  );
}
