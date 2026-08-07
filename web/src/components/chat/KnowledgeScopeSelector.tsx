import * as React from "react";
import { BookOpen } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { getKnowledgeBases, type KnowledgeBase } from "@/services/knowledgeService";
import { useChatStore } from "@/stores/chatStore";

export function KnowledgeScopeSelector() {
  const [bases, setBases] = React.useState<KnowledgeBase[]>([]);
  const [loaded, setLoaded] = React.useState(false);
  const selected = useChatStore((state) => state.knowledgeBaseIds);
  const setSelected = useChatStore((state) => state.setKnowledgeBaseIds);
  const isStreaming = useChatStore((state) => state.isStreaming);

  const load = React.useCallback(() => {
    if (loaded) return;
    setLoaded(true);
    getKnowledgeBases().then(setBases).catch(() => setBases([]));
  }, [loaded]);

  const toggle = (id: string, checked: boolean) => {
    setSelected(
      checked ? [...new Set([...selected, id])] : selected.filter((item) => item !== id)
    );
  };

  return (
    <DropdownMenu onOpenChange={(open) => open && load()}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={isStreaming}
          className="inline-flex items-center gap-1.5 rounded-lg border border-transparent bg-[#F5F5F5] px-3 py-1.5 text-xs font-medium text-[#6B7280] transition-colors hover:bg-[#EEEEEE] disabled:opacity-60"
        >
          <BookOpen className="h-3.5 w-3.5" />
          {selected.length ? `知识范围 ${selected.length}` : "全部知识库"}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>检索知识范围</DropdownMenuLabel>
        <DropdownMenuCheckboxItem
          checked={selected.length === 0}
          onCheckedChange={() => setSelected([])}
        >
          全部知识库
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {bases.length ? (
          bases.map((base) => (
            <DropdownMenuCheckboxItem
              key={base.id}
              checked={selected.includes(String(base.id))}
              onSelect={(event) => event.preventDefault()}
              onCheckedChange={(checked) => toggle(String(base.id), Boolean(checked))}
            >
              <span className="truncate">{base.name}</span>
            </DropdownMenuCheckboxItem>
          ))
        ) : (
          <div className="px-2 py-3 text-center text-xs text-muted-foreground">
            暂无可选知识库
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
