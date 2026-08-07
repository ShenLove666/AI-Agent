import * as React from "react";
import { differenceInCalendarDays, isValid } from "date-fns";
import {
  LogOut,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Settings,
  Trash2,
  X
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Loading } from "@/components/common/Loading";
import { BrandMark } from "@/components/brand/BrandMark";
import { BRAND_NAME, BRAND_SHORT_NAME } from "@/config/brand";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const {
    sessions,
    currentSessionId,
    isLoading,
    sessionsLoaded,
    createSession,
    deleteSession,
    renameSession,
    selectSession,
    fetchSessions
  } = useChatStore();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const [query, setQuery] = React.useState("");
  const [renamingId, setRenamingId] = React.useState<string | null>(null);
  const [renameValue, setRenameValue] = React.useState("");
  const [deleteTarget, setDeleteTarget] = React.useState<{
    id: string;
    title: string;
  } | null>(null);
  const [avatarFailed, setAvatarFailed] = React.useState(false);
  const renameInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    if (sessions.length === 0) {
      fetchSessions().catch(() => null);
    }
  }, [fetchSessions, sessions.length]);

  const filteredSessions = React.useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return sessions;
    return sessions.filter((session) => {
      const title = (session.title || "新对话").toLowerCase();
      return title.includes(keyword) || session.id.toLowerCase().includes(keyword);
    });
  }, [query, sessions]);

  const groupedSessions = React.useMemo(() => {
    const now = new Date();
    const groups = new Map<string, typeof filteredSessions>();
    const order: string[] = [];

    const resolveLabel = (value?: string) => {
      const parsed = value ? new Date(value) : now;
      const date = isValid(parsed) ? parsed : now;
      const diff = Math.max(0, differenceInCalendarDays(now, date));
      if (diff === 0) return "今天";
      if (diff <= 7) return "7天内";
      if (diff <= 30) return "30天内";
      return "更早";
    };

    filteredSessions.forEach((session) => {
      const label = resolveLabel(session.lastTime);
      if (!groups.has(label)) {
        groups.set(label, []);
        order.push(label);
      }
      groups.get(label)?.push(session);
    });

    return order.map((label) => ({
      label,
      items: groups.get(label) || []
    }));
  }, [filteredSessions]);

  React.useEffect(() => {
    if (renamingId) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [renamingId]);

  React.useEffect(() => {
    setAvatarFailed(false);
  }, [user?.avatar, user?.userId]);

  const avatarUrl = user?.avatar?.trim();
  const showAvatar = Boolean(avatarUrl) && !avatarFailed;
  const avatarFallback = (user?.username || user?.userId || "用户").slice(0, 1).toUpperCase();
  const startRename = (id: string, title: string) => {
    setRenamingId(id);
    setRenameValue(title || "新对话");
  };

  const cancelRename = () => {
    setRenamingId(null);
    setRenameValue("");
  };

  const commitRename = async () => {
    if (!renamingId) return;
    const nextTitle = renameValue.trim();
    if (!nextTitle) {
      cancelRename();
      return;
    }
    const currentTitle = sessions.find((session) => session.id === renamingId)?.title || "新对话";
    if (nextTitle === currentTitle) {
      cancelRename();
      return;
    }
    await renameSession(renamingId, nextTitle);
    cancelRename();
  };

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-30 bg-[var(--merchant-navy)]/45 transition-opacity lg:hidden",
          isOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed left-0 top-0 z-40 flex h-[100dvh] w-[min(88vw,280px)] flex-shrink-0 flex-col border-r border-white/10 bg-[var(--merchant-navy)] p-3 text-white shadow-2xl transition-transform lg:static lg:w-[272px] lg:translate-x-0 lg:shadow-none",
          isOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="主导航"
      >
        <div className="border-b border-white/10 pb-3">
          <div className="flex items-center gap-3">
            <BrandMark inverted />
            <div className="min-w-0">
              <p className="truncate text-base font-semibold">{BRAND_SHORT_NAME}</p>
              <p className="truncate text-xs text-slate-300">{BRAND_NAME}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded-lg p-1.5 text-slate-300 hover:bg-white/10 hover:text-white lg:hidden"
              aria-label="关闭主导航"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="space-y-3 py-3">
          <nav aria-label="工作区快捷入口" className="rounded-[var(--merchant-radius-md)] border border-white/10 bg-white/[0.05] p-2.5">
              <p className="px-1 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">工作区</p>
              <button
                type="button"
                className="flex w-full items-center gap-3 rounded-[10px] bg-[var(--merchant-cyan)] px-3 py-2.5 text-left font-semibold text-[var(--merchant-navy)] transition-colors hover:bg-[#43d2df]"
                onClick={() => {
                  createSession().catch(() => null);
                  navigate("/chat");
                  onClose();
                }}
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--merchant-navy)]/15">
                  <Plus className="h-4 w-4" />
                </span>
                <span className="flex-1">
                  <span className="block text-sm">新建售后咨询</span>
                  <span className="block text-[11px] font-normal opacity-70">核对规则与处理边界</span>
                </span>
              </button>
              {user?.role === "admin" ? (
                <button
                  type="button"
                  className="mt-2 inline-flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10"
                  onClick={() => {
                    window.open("/admin", "_blank");
                    onClose();
                  }}
                >
                  <Settings className="h-3.5 w-3.5" />
                  打开管理后台
                </button>
              ) : null}
          </nav>
          <div>
            <label htmlFor="session-search" className="px-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">历史会话</label>
            <div className="mt-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="session-search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索售后会话"
                  className="h-10 w-full rounded-[10px] border border-white/10 bg-white/[0.06] pl-9 pr-3 text-sm text-white placeholder:text-slate-400 focus:border-[var(--merchant-cyan)] focus:outline-none focus:ring-2 focus:ring-[var(--merchant-focus)]"
                />
              </div>
            </div>
          </div>
        </div>
        <div className="relative flex-1 min-h-0">
          <div className="h-full overflow-y-auto sidebar-scroll">
            {sessions.length === 0 && (!sessionsLoaded || isLoading) ? (
              <div className="flex h-full items-center justify-center text-slate-400">
                <Loading label="加载会话中" />
              </div>
            ) : filteredSessions.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-slate-400">
                <MessageSquare className="h-10 w-10" />
                <p className="mt-2 text-sm">暂无售后会话</p>
              </div>
            ) : (
              <div>
                {groupedSessions.map((group, index) => (
                  <div key={group.label} className={cn("flex flex-col", index === 0 ? "mt-0" : "mt-4")}>
                    <p className="mb-1.5 pl-3 text-[11px] font-medium leading-[18px] text-slate-400">
                      {group.label}
                    </p>
                    {group.items.map((session) => (
                      <div
                        key={session.id}
                        className={cn(
                          "group my-[1px] flex min-h-[40px] cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-[14px] leading-[22px] transition-colors duration-200",
                          currentSessionId === session.id
                            ? "bg-white/12 text-white"
                            : "text-slate-300 hover:bg-white/[0.07] hover:text-white"
                        )}
                        role="button"
                        tabIndex={0}
                        onClick={() => {
                          if (renamingId === session.id) return;
                          if (renamingId) {
                            cancelRename();
                          }
                          selectSession(session.id).catch(() => null);
                          navigate(`/chat/${session.id}`);
                          onClose();
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            selectSession(session.id).catch(() => null);
                            navigate(`/chat/${session.id}`);
                            onClose();
                          }
                        }}
                      >
                        {renamingId === session.id ? (
                          <input
                            ref={renameInputRef}
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                commitRename().catch(() => null);
                              }
                              if (event.key === "Escape") {
                                event.preventDefault();
                                cancelRename();
                              }
                            }}
                            onBlur={() => {
                              commitRename().catch(() => null);
                            }}
                            className="h-7 flex-1 rounded-md border border-[var(--merchant-cyan)] bg-[var(--merchant-navy)] px-2 text-sm leading-[22px] text-white focus:outline-none focus:ring-2 focus:ring-[var(--merchant-focus)]"
                          />
                        ) : (
                          <span className="min-w-0 flex-1 truncate font-normal">
                            {session.title || "新对话"}
                          </span>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className={cn(
                                "flex h-6 w-6 items-center justify-center rounded text-slate-300 transition-opacity duration-150 hover:bg-white/10 hover:text-white",
                                currentSessionId === session.id
                                  ? "pointer-events-auto opacity-100 text-white"
                                  : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100"
                              )}
                              onClick={(event) => event.stopPropagation()}
                              aria-label="会话操作"
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            align="start"
                            className="min-w-[120px] rounded-lg border-0 bg-white p-0 py-1 shadow-[0_4px_16px_rgba(0,0,0,0.12)]"
                          >
                            <DropdownMenuItem
                              onClick={(event) => {
                                event.stopPropagation();
                                startRename(session.id, session.title || "新对话");
                              }}
                              className="px-4 py-2 text-[14px] text-[#333333] focus:bg-[#F5F5F5] focus:text-[#333333] data-[highlighted]:bg-[#F5F5F5] data-[highlighted]:text-[#333333]"
                            >
                              <Pencil className="mr-2 h-4 w-4" />
                              重命名
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(event) => {
                                event.stopPropagation();
                                setDeleteTarget({
                                  id: session.id,
                                  title: session.title || "新对话"
                                });
                              }}
                              className="px-4 py-2 text-[14px] text-[#FF4D4F] focus:bg-[#F5F5F5] focus:text-[#FF4D4F] data-[highlighted]:bg-[#F5F5F5] data-[highlighted]:text-[#FF4D4F]"
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              删除
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-5 bg-gradient-to-b from-transparent to-[var(--merchant-navy)]"
          />
        </div>
        <div className="mt-auto pt-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-[10px] border border-white/10 bg-white/[0.05] p-2 text-left transition-colors hover:bg-white/10 data-[state=open]:bg-white/10"
                aria-label="用户菜单"
              >
                <div className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-[var(--merchant-cyan)] font-semibold text-[var(--merchant-navy)]">
                  {showAvatar ? (
                    <img
                      src={avatarUrl}
                      alt={user?.username || user?.userId || "用户"}
                      className="h-full w-full object-cover"
                      onError={() => setAvatarFailed(true)}
                    />
                  ) : (
                    <span className="text-sm font-medium">{avatarFallback}</span>
                  )}
                </div>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-white">{(() => {
                    const fallback = user?.username || user?.userId || "用户";
                    return /^\d+$/.test(fallback) ? "用户" : fallback;
                  })()}</span>
                  <span className="block text-[10px] text-slate-400">{user?.role === "admin" ? "平台管理员" : "商家运营"}</span>
                </span>
                <MoreHorizontal className="h-4 w-4 text-slate-400" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" sideOffset={8} className="w-48">
              <DropdownMenuItem onClick={() => logout()} className="text-rose-600 focus:text-rose-600">
                <LogOut className="mr-2 h-4 w-4" />
                退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => {
        if (!open) {
          setDeleteTarget(null);
        }
      }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除该会话？</AlertDialogTitle>
            <AlertDialogDescription>
              [{deleteTarget?.title || "该会话"}] 将被永久删除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleteTarget) return;
                const target = deleteTarget;
                const isCurrent = currentSessionId === target.id;
                setDeleteTarget(null);
                deleteSession(target.id)
                  .then(() => {
                    if (isCurrent) {
                      navigate("/chat");
                    }
                  })
                  .catch(() => null);
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
