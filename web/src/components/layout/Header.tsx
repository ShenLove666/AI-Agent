import { Menu, ShieldCheck } from "lucide-react";

import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui/button";
import { BRAND_SHORT_NAME } from "@/config/brand";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";

interface HeaderProps {
  onToggleSidebar: () => void;
}

export function Header({ onToggleSidebar }: HeaderProps) {
  const { currentSessionId, sessions } = useChatStore();
  const user = useAuthStore((state) => state.user);
  const currentSession = sessions.find((session) => session.id === currentSessionId);
  const roleLabel = user?.role === "admin" ? "平台管理员" : "商家运营";

  return (
    <header className="relative z-20 shrink-0 border-b border-[var(--merchant-border)] bg-white shadow-[0_1px_4px_rgba(8,43,69,0.04)]">
      <div className="flex h-[var(--merchant-header-height)] min-w-0 items-center justify-between gap-3 px-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleSidebar}
            aria-label="打开主导航"
            className="shrink-0 text-[var(--merchant-navy)] hover:bg-[var(--merchant-cyan-soft)] lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-2 lg:hidden">
            <BrandMark className="h-8 w-8 rounded-[9px]" />
            <span className="hidden text-sm font-semibold text-[var(--merchant-navy)] min-[390px]:inline">
              {BRAND_SHORT_NAME}
            </span>
          </div>
          <div className="min-w-0 border-l border-[var(--merchant-border)] pl-3 lg:border-l-0 lg:pl-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--merchant-text-muted)]">
              商家售后工作区
            </p>
            <p className="truncate text-sm font-semibold text-[var(--merchant-text)] sm:text-base">
              {currentSession?.title || "新建售后咨询"}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded-full border border-[var(--merchant-border)] bg-[var(--merchant-surface-subtle)] px-2.5 py-1.5 text-xs text-[var(--merchant-text-muted)] sm:px-3">
          <ShieldCheck className="h-3.5 w-3.5 text-[var(--merchant-cyan-strong)]" />
          <span className="hidden sm:inline">{user?.username || "当前账号"}</span>
          <span className="font-semibold text-[var(--merchant-navy)]">{roleLabel}</span>
        </div>
      </div>
    </header>
  );
}
