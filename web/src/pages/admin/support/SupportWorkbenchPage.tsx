import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  FileText,
  Inbox,
  Loader2,
  Package,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Truck,
  UserRoundCheck
} from "lucide-react";
import { toast } from "sonner";
import { MarkdownRenderer } from "@/components/chat/MarkdownRenderer";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { CaseProvenanceView } from "./CaseProvenanceView";
import {
  assignSupportCase,
  decideSupportSuggestion,
  generateSupportSuggestion,
  getSupportCase,
  getSupportCases,
  getSupportMetrics,
  getSupportWorkspace,
  raiseSupportEscalation,
  sendManualReply,
  transitionSupportCase,
  type CaseStatus,
  type SupportCaseDetail,
  type SupportCaseSummary,
  type SupportMetrics,
  type SupportWorkspace
} from "@/services/supportService";
import { useAuthStore } from "@/stores/authStore";

const statuses: Record<CaseStatus, string> = {
  pending: "待处理",
  in_progress: "处理中",
  resolved: "已解决",
  escalated: "已升级"
};
const priorities = { low: "低", normal: "普通", high: "高", urgent: "紧急" };
const riskLabels = { low: "低", medium: "中", high: "高" } as const;
const statusTone: Record<CaseStatus, string> = {
  pending: "bg-blue-50 text-blue-700",
  in_progress: "bg-amber-50 text-amber-700",
  resolved: "bg-emerald-50 text-emerald-700",
  escalated: "bg-rose-50 text-rose-700"
};
const priorityTone = {
  low: "text-slate-500",
  normal: "text-slate-600",
  high: "text-orange-600",
  urgent: "text-rose-600"
};
const fulfillmentStatuses: Record<string, string> = {
  pending: "待履约",
  preparing: "备货中",
  delivering: "配送中",
  delivered: "已送达",
  cancelled: "已取消"
};
const riskTone: Record<"low" | "medium" | "high", string> = {
  low: "border-emerald-200 bg-emerald-50 text-emerald-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  high: "border-rose-200 bg-rose-50 text-rose-700"
};
type ResolutionFact = { type: string; content: string; orderNo?: string };
/**
 * 后端并行演进中的 resolution 扩展字段（rules / citationGroups）。
 * 以可选字段接入并做运行时容错：后端尚未下发时对应区块自动隐藏。
 */
interface ResolutionWithExtras {
  intent: string;
  risk: "low" | "medium" | "high";
  facts: ResolutionFact[];
  missingFacts: string[];
  recommendedActions: string[];
  draftReply: string;
  citations: string[];
  canSend: boolean;
  escalationReason: string | null;
  terminalState: string;
  rules?: Array<{ title?: string; content?: string } | string>;
  citationGroups?: {
    orderFacts?: Array<ResolutionFact | string>;
    rules?: Array<{ title?: string; content?: string } | string>;
  };
}
const evidenceItemText = (item: unknown): string => {
  if (typeof item === "string") return item;
  const value = item as {
    content?: string;
    title?: string;
    docName?: string;
    releaseVersion?: string;
  };
  return (
    value.content ||
    value.title ||
    value.docName ||
    (value.releaseVersion ? `发布版本 ${value.releaseVersion}` : "")
  );
};

function GeneratingSuggestionStatus() {
  // 前端只发一次 generateSupportSuggestion() HTTP 请求，没有真实阶段事件；
  // 固定打勾的步骤是假进度——只显示 spinner + 说明文案
  return (
    <div
      role="status"
      aria-label="AI 正在处理"
      className="space-y-3 rounded-md border border-indigo-100 bg-indigo-50/50 p-4"
    >
      <p className="flex items-center gap-2 text-sm font-semibold text-indigo-900">
        <Loader2 className="h-4 w-4 animate-spin text-indigo-600" />
        AI 正在生成处理建议…
      </p>
      <p className="text-xs leading-5 text-slate-500">
        正在核对工单、业务事实与已发布知识
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  caption,
  tone
}: {
  label: string;
  value: string;
  caption: string;
  tone: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-slate-500">{label}</p>
        <span className={cn("h-2 w-2 rounded-full", tone)} />
      </div>
      <strong className="mt-1.5 block text-xl font-semibold text-slate-900">{value}</strong>
      <span className="text-xs text-slate-400">{caption}</span>
    </div>
  );
}

function CaseRow({
  item,
  active,
  onClick
}: {
  item: SupportCaseSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full border-b border-slate-100 p-3.5 text-left transition hover:bg-slate-50",
        active && "bg-indigo-50 shadow-[inset_2px_0_0_#4F46E5]"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {item.unread && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-500" />}
            <p className="truncate text-[13px] font-semibold text-slate-900">{item.subject}</p>
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {item.customerName} · {item.lastMessage}
          </p>
        </div>
        <span className={cn("text-[11px] font-medium", priorityTone[item.priority])}>
          {priorities[item.priority]}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span
          className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", statusTone[item.status])}
        >
          {statuses[item.status]}
        </span>
        <span className="text-[10px] text-slate-400">{item.caseKey}</span>
      </div>
    </button>
  );
}

export function SupportWorkbenchPage() {
  const user = useAuthStore((s) => s.user);
  const [cases, setCases] = useState<SupportCaseSummary[]>([]);
  const [detail, setDetail] = useState<SupportCaseDetail | null>(null);
  const [metrics, setMetrics] = useState<SupportMetrics | null>(null);
  const [workspace, setWorkspace] = useState<SupportWorkspace | null>(null);
  const [status, setStatus] = useState<string>("pending");
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState("");
  const [edited, setEdited] = useState("");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  // 订单上下文默认折叠为摘要（工作台最宝贵的是 AI 建议的垂直空间），点开才看详情
  const [orderExpanded, setOrderExpanded] = useState(false);
  // AI 回复建议正文滚动容器（生成完成后滚回顶部，不用 scrollIntoView——
  // 后者可能连带移动外层 Admin 页面的祖先滚动容器）
  const aiBodyRef = useRef<HTMLDivElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [generatingSuggestion, setGeneratingSuggestion] = useState(false);
  const [sendingReply, setSendingReply] = useState(false);
  const [updatingCase, setUpdatingCase] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [confirmedFacts, setConfirmedFacts] = useState(false);
  // Detail/workspace requests are independent HTTP calls.  Sequence guards
  // prevent a slower click or refresh from repainting the case selected later.
  const caseRequestIdRef = useRef(0);
  const loadRequestIdRef = useRef(0);
  const actionRequestIdRef = useRef(0);
  const actionSetterRequestRef = useRef(new Map<(value: boolean) => void, number>());
  const activeCaseIdRef = useRef<number | null>(null);

  const selectCase = useCallback(async (id: number) => {
    const requestId = ++caseRequestIdRef.current;
    // Invalidate actions against the previously visible case immediately;
    // their eventual errors must not surface after the user changed cases.
    actionRequestIdRef.current += 1;
    activeCaseIdRef.current = null;
    try {
      const [value, context] = await Promise.all([getSupportCase(id), getSupportWorkspace(id)]);
      if (requestId !== caseRequestIdRef.current) return;
      activeCaseIdRef.current = id;
      setDetail(value);
      setWorkspace(context);
      const suggestion = value.suggestions.find((x) => !x.decision);
      setEdited(suggestion?.content || "");
      setEvidenceOpen(false);
      setConfirmedFacts(false);
      setOrderExpanded(false);
    } catch (error) {
      if (requestId === caseRequestIdRef.current) {
        toast.error((error as Error).message || "工单详情加载失败");
      }
    }
  }, []);
  const load = useCallback(async () => {
    const requestId = ++loadRequestIdRef.current;
    // A refresh supersedes any detail request started before it.
    caseRequestIdRef.current += 1;
    actionRequestIdRef.current += 1;
    setLoading(true);
    try {
      const [items, summary] = await Promise.all([
        getSupportCases({ status: status || undefined, search: search || undefined }),
        getSupportMetrics()
      ]);
      if (requestId !== loadRequestIdRef.current) return;
      setCases(items);
      setMetrics(summary);
      if (items.length) {
        const id = items.some((x) => x.id === detail?.id) ? detail!.id : items[0].id;
        await selectCase(id);
      } else if (requestId === loadRequestIdRef.current) {
        activeCaseIdRef.current = null;
        setDetail(null);
        setWorkspace(null);
      }
    } catch (e) {
      if (requestId === loadRequestIdRef.current) {
        toast.error((e as Error).message || "工单加载失败");
      }
    } finally {
      if (requestId === loadRequestIdRef.current) setLoading(false);
    }
  }, [detail?.id, search, status, selectCase]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [search, status]); // eslint-disable-line react-hooks/exhaustive-deps
  const runCaseAction = async <T,>(
    setter: (value: boolean) => void,
    fn: () => Promise<T>,
    message: string,
    refresh = true
  ) => {
    const actionRequestId = ++actionRequestIdRef.current;
    const targetCaseId = detail?.id ?? null;
    const isCurrentAction = () =>
      actionRequestId === actionRequestIdRef.current &&
      (targetCaseId === null || activeCaseIdRef.current === targetCaseId);
    actionSetterRequestRef.current.set(setter, actionRequestId);
    setter(true);
    try {
      await fn();
      if (refresh && targetCaseId !== null) {
        const [next, nextWorkspace, nextMetrics] = await Promise.all([
          getSupportCase(targetCaseId),
          getSupportWorkspace(targetCaseId),
          getSupportMetrics()
        ]);
        if (!isCurrentAction()) return;
        setDetail(next);
        setWorkspace(nextWorkspace);
        setCases((list) => list.map((x) => (x.id === next.id ? next : x)));
        setMetrics(nextMetrics);
        setEdited(next.suggestions.find((x) => !x.decision)?.content || "");
      }
      if (isCurrentAction()) toast.success(message);
    } catch (e) {
      if (isCurrentAction()) toast.error((e as Error).message || "操作失败");
    } finally {
      if (actionSetterRequestRef.current.get(setter) === actionRequestId) {
        actionSetterRequestRef.current.delete(setter);
        setter(false);
      }
    }
  };
  const suggestion = detail?.suggestions.find((x) => !x.decision) || null;
  const cards = useMemo(
    () =>
      [
        [
          "待处理",
          `${metrics?.pendingCases ?? "--"}`,
          `共 ${metrics?.totalCases ?? 0} 条`,
          "bg-blue-400"
        ],
        [
          "解决率",
          metrics?.resolutionRate == null ? "--" : `${metrics.resolutionRate}%`,
          "来自真实状态事件",
          "bg-emerald-400"
        ],
        [
          "AI 采纳率",
          metrics?.acceptanceRate == null ? "--" : `${metrics.acceptanceRate}%`,
          "含人工修订发送",
          "bg-violet-400"
        ],
        [
          "引用覆盖",
          metrics?.citationCoverage == null ? "--" : `${metrics.citationCoverage}%`,
          "已生成建议",
          "bg-amber-400"
        ]
      ] as const,
    [metrics]
  );
  return (
    <div className="mx-auto max-w-[1680px] space-y-4 pb-8">
      <section className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">客服工作台</h1>
            {metrics?.provenance === "demo" && (
              <Badge variant="outline" className="font-normal">
                演示数据 · 指标由工单事件计算
              </Badge>
            )}
          </div>
          <p className="text-sm text-slate-500">
            处理顾客问题、审核 AI 回复，并把失败案例沉淀为知识改进任务。
          </p>
        </div>
        <Button variant="outline" className="gap-2" onClick={() => void load()}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          刷新
        </Button>
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        {cards.map(([a, b, c, d]) => (
          <Metric key={a} label={a} value={b} caption={c} tone={d} />
        ))}
      </section>
      <section
        aria-label="客服处理工作区"
        className="grid h-auto min-h-0 overflow-visible rounded-lg border border-slate-200 bg-white xl:h-[calc(100dvh-240px)] xl:min-h-[560px] xl:grid-cols-[290px_minmax(500px,1fr)_440px] xl:overflow-hidden 2xl:grid-cols-[300px_minmax(560px,1fr)_500px]"
      >
        <aside
          role="region"
          aria-label="工单队列"
          className="flex min-h-[420px] flex-col border-b border-slate-200 bg-white xl:min-h-0 xl:border-b-0 xl:border-r"
        >
          <div className="shrink-0 border-b border-slate-200 p-4">
            <div className="flex items-center gap-2">
              <Inbox className="h-4 w-4 text-indigo-600" />
              <h2 className="text-sm font-semibold text-slate-900">工单队列</h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {cases.length}
              </span>
            </div>
            <div className="relative mt-4">
              <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索顾客、主题或工单号"
                className="bg-slate-50 pl-9"
              />
            </div>
            <div className="mt-3 grid grid-cols-4 gap-1 rounded-xl bg-slate-100 p-1">
              {(["pending", "in_progress", "escalated", ""] as const).map((value) => (
                <button
                  key={value || "all"}
                  onClick={() => setStatus(value)}
                  className={cn(
                    "rounded-lg px-1 py-2 text-[11px] text-slate-500",
                    status === value && "bg-white font-semibold text-slate-900 shadow-sm"
                  )}
                >
                  {value ? statuses[value] : "全部"}
                </button>
              ))}
            </div>
          </div>
          {/* 唯一纵向滚动容器：工单列表（每栏只允许一个滚动区） */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex h-40 items-center justify-center">
                <Loader2 className="animate-spin text-blue-500" />
              </div>
            ) : (
              cases.map((item) => (
                <CaseRow
                  key={item.id}
                  item={item}
                  active={detail?.id === item.id}
                  onClick={() => void selectCase(item.id)}
                />
              ))
            )}
          </div>
        </aside>
        <main
          role="region"
          aria-label="工单对话"
          className="flex min-h-[640px] min-w-0 flex-col border-b border-slate-200 bg-slate-50/40 xl:min-h-0 xl:border-b-0"
        >
          {detail ? (
            <>
              <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 bg-white p-5">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-slate-950">{detail.subject}</h2>
                    <Badge variant="outline">{detail.isDemo ? "DEMO" : "LIVE"}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {detail.customerName} · {detail.channel.toUpperCase()} · {detail.caseKey}
                  </p>
                </div>
                <div className="flex gap-2">
                  {!detail.assigneeId && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={updatingCase || !user?.userId}
                      onClick={() =>
                        user?.userId &&
                        void runCaseAction(
                          setUpdatingCase,
                          () => assignSupportCase(detail.id, Number(user.userId), detail.version),
                          "已接单"
                        )
                      }
                    >
                      <UserRoundCheck className="mr-1 h-4 w-4" />
                      接单
                    </Button>
                  )}
                  {detail.status !== "resolved" && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-emerald-700"
                      disabled={updatingCase}
                      onClick={() =>
                        void runCaseAction(
                          setUpdatingCase,
                          () =>
                            transitionSupportCase(detail.id, "resolved", detail.version, {
                              resolutionCode: "policy_explained",
                              resolutionNote: "已依据规则完成答复"
                            }),
                          "工单已解决"
                        )
                      }
                    >
                      <CheckCircle2 className="mr-1 h-4 w-4" />
                      解决
                    </Button>
                  )}
                </div>
              </header>
              <div className="flex-1 space-y-5 overflow-visible p-5 xl:min-h-0 xl:overflow-auto">
                <CaseProvenanceView
                  value={
                    detail.provenance
                      ? {
                          ...detail.provenance,
                          caseId: detail.id,
                          caseKey: detail.caseKey,
                          isDemo: detail.isDemo
                        }
                      : null
                  }
                />
                {detail.messages.map((message) => (
                  <div
                    key={message.id}
                    className={cn("flex gap-3", message.role === "agent" && "flex-row-reverse")}
                  >
                    <div
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                        message.role === "agent"
                          ? "bg-blue-600 text-white"
                          : "bg-slate-200 text-slate-700"
                      )}
                    >
                      {message.role === "agent" ? (
                        <Bot className="h-4 w-4" />
                      ) : (
                        detail.customerName.slice(0, 1)
                      )}
                    </div>
                    <div className={cn("max-w-[78%]", message.role === "agent" && "text-right")}>
                      <p className="mb-1 text-[11px] text-slate-400">
                        {message.role === "agent" ? "客服" : detail.customerName}
                      </p>
                      <div
                        className={cn(
                          "rounded-lg px-4 py-2.5 text-left text-sm leading-6",
                          message.role === "agent"
                            ? "rounded-tr-sm border border-blue-100 bg-white text-slate-800"
                            : "rounded-tl-sm border border-slate-200 bg-white text-slate-700"
                        )}
                      >
                        {message.role === "agent" ? (
                          <MarkdownRenderer content={message.content || ""} />
                        ) : (
                          <p className="whitespace-pre-wrap">{message.content}</p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="m-4 rounded-lg border border-slate-200 bg-white p-3">
                <Textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="输入人工回复，或使用右侧 AI 建议…"
                  className="min-h-[76px] resize-none border-0 p-0 shadow-none focus-visible:ring-0"
                />
                <div className="flex justify-end border-t pt-3">
                  <Button
                    size="sm"
                    disabled={sendingReply || !draft.trim()}
                    onClick={() =>
                      void runCaseAction(
                        setSendingReply,
                        async () => {
                          const value = await sendManualReply(detail.id, draft);
                          setDraft("");
                          return value;
                        },
                        "回复已记录"
                      )
                    }
                  >
                    <Send className="mr-2 h-4 w-4" />
                    发送回复
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-slate-400">
              选择工单开始处理
            </div>
          )}
        </main>
        <aside
          role="region"
          aria-label="AI 回复助手"
          className="flex min-h-[680px] flex-col bg-slate-50/60 xl:min-h-0 xl:border-l xl:border-slate-200"
        >
          {/* 订单上下文：默认摘要（~110px），「查看订单详情」才展开——
              工作台核心是 AI 建议，订单卡不该占 40% 高度；右侧只保留
              AI 正文一个纵向滚动容器（此处无滚动） */}
          <section className="shrink-0 border-b border-slate-200 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="rounded-md border border-indigo-100 bg-indigo-50 p-1.5 text-indigo-600">
                  <Package className="h-4 w-4" />
                </span>
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">订单上下文</h2>
                  <p className="text-[11px] text-slate-400">客服判断所需的交易事实</p>
                </div>
              </div>
              {workspace?.order?.isDemo && (
                <Badge variant="outline" className="border-slate-200 text-slate-500">
                  模拟订单
                </Badge>
              )}
            </div>
            {workspace?.order ? (
              <div className="mt-3 space-y-2 rounded-md border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-xs font-semibold text-slate-900">
                      {workspace.order.orderNo}
                    </p>
                    <p className="mt-0.5 truncate text-[11px] text-slate-500">
                      {workspace.order.items
                        .map((item) => `${item.productName} ×${item.quantity}`)
                        .join("、")}
                    </p>
                  </div>
                  <strong className="shrink-0 text-sm text-slate-900">
                    ¥{(workspace.order.amount.minor / 100).toFixed(2)}
                  </strong>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                  <span className="flex items-center gap-1">
                    <Truck className="h-3.5 w-3.5 text-indigo-500" />
                    {fulfillmentStatuses[workspace.order.fulfillment?.status || ""] || "暂无履约"}
                  </span>
                  <span>·</span>
                  <span>{workspace.order.refund?.status || "无退款申请"}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setOrderExpanded((prev) => !prev)}
                  aria-expanded={orderExpanded}
                  className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800"
                >
                  {orderExpanded ? "收起订单详情" : "查看订单详情"}
                  <ChevronDown
                    className={cn("h-3.5 w-3.5 transition-transform", orderExpanded && "rotate-180")}
                  />
                </button>
                {orderExpanded ? (
                  <div className="space-y-2 border-t border-slate-100 pt-2 text-xs">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-md bg-slate-50 p-2">
                        <span className="text-slate-400">履约状态</span>
                        <p className="mt-0.5 font-medium text-slate-800">
                          {fulfillmentStatuses[workspace.order.fulfillment?.status || ""] || "暂无履约"}
                        </p>
                      </div>
                      <div className="rounded-md bg-slate-50 p-2">
                        <span className="text-slate-400">退款状态</span>
                        <p className="mt-0.5 font-medium text-slate-800">
                          {workspace.order.refund?.status || "无退款申请"}
                        </p>
                      </div>
                    </div>
                    <p className="text-[10px] leading-4 text-slate-400">
                      {workspace.order.fulfillment?.currentLocation
                        ? `当前位置：${workspace.order.fulfillment.currentLocation}`
                        : "当前位置未接入，不展示虚构轨迹"}
                    </p>
                    {workspace?.outboundMessages[0] && (
                      <p className="text-[11px] text-slate-500">
                        最近发送：
                        {workspace.outboundMessages[0].isDemo ? "模拟发送" : "外部渠道"} ·{" "}
                        {workspace.outboundMessages[0].status}
                      </p>
                    )}
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="mt-3 rounded-md bg-white p-3 text-xs text-slate-500">
                当前工单未关联订单，可继续按知识规则处理。
              </p>
            )}
          </section>
          <header className="flex shrink-0 items-center justify-between border-b border-indigo-100 bg-indigo-50/50 px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="rounded-md border border-indigo-200 bg-white p-1.5 text-indigo-600 shadow-sm">
                <Sparkles className="h-4 w-4" />
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-slate-900">AI 回复建议</h2>
                  <span className="rounded-full border border-indigo-200 bg-indigo-50 px-1.5 py-px text-[10px] font-medium text-indigo-600">
                    AI
                  </span>
                </div>
                <p className="text-[11px] text-slate-400">已发布知识 · 人工审核</p>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="border-indigo-200 bg-white text-indigo-600 hover:bg-indigo-50"
              disabled={generatingSuggestion || !detail}
              onClick={async () => {
                if (!detail) return;
                setGeneratingSuggestion(true);
                try {
                  await generateSupportSuggestion(detail.id);
                  await selectCase(detail.id);
                  toast.success("建议生成完成");
                  requestAnimationFrame(() => {
                    // 只滚 AI 自己的内容区，不用 scrollIntoView（可能带动
                    // Admin 页面祖先滚动容器）
                    aiBodyRef.current?.scrollTo?.({ top: 0 });
                  });
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setGeneratingSuggestion(false);
                }
              }}
            >
              {generatingSuggestion ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-3.5 w-3.5" />
              )}
              生成
            </Button>
          </header>
          {/* 右侧唯一纵向滚动容器：AI 正文（订单区不再滚动） */}
          <section
            ref={aiBodyRef}
            aria-label="AI 回复建议正文"
            className="min-h-0 flex-1 overflow-y-auto p-4"
          >
            {generatingSuggestion ? (
              <GeneratingSuggestionStatus />
            ) : !suggestion ? (
              <div className="py-16 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border border-indigo-100 bg-indigo-50 text-indigo-600">
                  <Sparkles className="h-5 w-5" />
                </div>
                <h3 className="mt-3 text-sm font-semibold text-slate-900">先查规则，再拟回复</h3>
                <p className="mx-auto mt-1.5 max-w-[260px] text-xs leading-5 text-slate-500">
                  只引用当前已发布知识；资料不足会明确提示，不把猜测包装成答案。
                </p>
              </div>
            ) : suggestion.status !== "completed" ? (
              <div className="flex gap-3 rounded-md border border-amber-200 bg-amber-50 p-3.5">
                <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
                <div>
                  <p className="text-sm font-semibold text-amber-900">AI 建议暂不可用</p>
                  <p className="mt-1 text-xs leading-5 text-amber-700">
                    {suggestion.status === "insufficient_evidence"
                      ? "已发布知识不足，请补充规则或升级主管。"
                      : "模型服务未配置，仍可使用中间区域人工回复。"}
                  </p>
                </div>
              </div>
            ) : (
              (() => {
                const res = suggestion.resolution as ResolutionWithExtras | null;
                const groups = res?.citationGroups;
                const rulesCount = res?.rules?.length ?? groups?.rules?.length ?? 0;
                const orderFacts: Array<unknown> = groups?.orderFacts?.length
                  ? groups.orderFacts
                  : (res?.facts ?? []);
                const ruleItems: Array<unknown> = groups?.rules?.length
                  ? groups.rules
                  : suggestion.citations;
                return (
                  <div className="space-y-3.5">
                    {suggestion.riskFlags.length > 0 && (
                      <div className="flex gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
                        <ShieldCheck className="h-4 w-4 shrink-0" />
                        检测到退款、支付或安全风险，发送前必须人工确认
                      </div>
                    )}
                    {res && (
                      <section
                        aria-label="AI 处理建议"
                        className="space-y-2.5 rounded-md border border-indigo-100 bg-indigo-50/50 p-3 text-xs"
                      >
                        <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-900">
                          <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
                          AI 处理建议
                        </h3>
                        {res.facts?.length > 0 && (
                          <div className="rounded-md border border-emerald-100 bg-white p-2.5">
                            <p className="flex items-center gap-1.5 font-semibold text-emerald-700">
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              已核实事实
                            </p>
                            <ul className="mt-1.5 space-y-1 leading-5 text-slate-700">
                              {res.facts.map((fact, index) => (
                                <li key={index} className="flex gap-1.5">
                                  <span className="shrink-0 text-emerald-500">·</span>
                                  <span>
                                    {fact.type && (
                                      <span className="mr-1 font-medium text-slate-500">
                                        {fact.type}
                                      </span>
                                    )}
                                    {fact.content}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {res.missingFacts?.length > 0 && (
                          <div className="rounded-md border border-amber-100 bg-white p-2.5">
                            <p className="flex items-center gap-1.5 font-semibold text-amber-700">
                              <AlertTriangle className="h-3.5 w-3.5" />
                              待确认
                            </p>
                            <ul className="mt-1.5 space-y-1 leading-5 text-slate-700">
                              {res.missingFacts.map((fact, index) => (
                                <li key={index} className="flex gap-1.5">
                                  <span className="shrink-0 text-amber-500">!</span>
                                  {fact}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {rulesCount > 0 && (
                          <div className="flex items-center justify-between rounded-md border border-slate-200 bg-white p-2.5">
                            <p className="flex items-center gap-1.5 font-semibold text-slate-700">
                              <BookOpen className="h-3.5 w-3.5 text-indigo-500" />
                              适用规则
                            </p>
                            <span className="text-[11px] text-slate-500">
                              规则依据 {rulesCount}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-semibold text-slate-500">风险</span>
                          <Badge variant="outline" className={riskTone[res.risk]}>
                            {riskLabels[res.risk]}
                          </Badge>
                        </div>
                        {res.recommendedActions?.length > 0 && (
                          <div className="rounded-md bg-white p-2.5">
                            <p className="font-semibold text-slate-500">建议动作</p>
                            <ol className="mt-1.5 space-y-1 leading-5 text-slate-700">
                              {res.recommendedActions.map((item, index) => (
                                <li key={index} className="flex gap-1.5">
                                  <span className="shrink-0 font-medium text-slate-400">
                                    {index + 1}.
                                  </span>
                                  {item}
                                </li>
                              ))}
                            </ol>
                          </div>
                        )}
                      </section>
                    )}
                    <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-500">
                      <span className="h-px flex-1 bg-slate-200" />
                      对客回复草稿
                      <span className="h-px flex-1 bg-slate-200" />
                    </div>
                    <Textarea
                      aria-label="可编辑的对客回复"
                      value={edited}
                      onChange={(e) => setEdited(e.target.value)}
                      className="h-[180px] min-h-[120px] max-h-[240px] resize-y overflow-y-auto rounded-md border-indigo-100 bg-white leading-6 text-slate-800 placeholder:text-slate-400 focus-visible:ring-indigo-200"
                    />
                    <div>
                      <button
                        type="button"
                        aria-expanded={evidenceOpen}
                        aria-controls={`suggestion-evidence-${suggestion.id}`}
                        className="flex w-full items-center gap-2 rounded-md py-1 text-left text-xs font-semibold text-slate-500 hover:text-slate-700"
                        onClick={() => setEvidenceOpen((open) => !open)}
                      >
                        <FileText className="h-4 w-4" />
                        <span className="flex-1">处理依据</span>
                        <ChevronDown
                          className={cn("h-4 w-4 transition-transform", evidenceOpen && "rotate-180")}
                        />
                      </button>
                      {evidenceOpen && (
                        <div id={`suggestion-evidence-${suggestion.id}`} className="mt-2">
                          {orderFacts.length > 0 && (
                            <div className="mb-3">
                              <p className="mb-1.5 flex items-center justify-between text-[11px] font-semibold text-slate-500">
                                <span>订单事实</span>
                                <span className="rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-500">
                                  {orderFacts.length}
                                </span>
                              </p>
                              {orderFacts.map((item, index) => (
                                <div
                                  key={index}
                                  className="mb-2 flex gap-2 rounded-md border border-slate-200 bg-white p-2.5"
                                >
                                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-50 text-[10px] font-medium text-indigo-600">
                                    {index + 1}
                                  </span>
                                  <p className="line-clamp-3 text-xs leading-5 text-slate-600">
                                    {evidenceItemText(item)}
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}
                          {ruleItems.length > 0 && (
                            <div>
                              <p className="mb-1.5 flex items-center justify-between text-[11px] font-semibold text-slate-500">
                                <span>规则依据</span>
                                <span className="rounded-full bg-slate-100 px-1.5 py-px text-[10px] text-slate-500">
                                  {ruleItems.length}
                                </span>
                              </p>
                              {ruleItems.map((item, index) => (
                                <div
                                  key={index}
                                  className="mb-2 flex gap-2 rounded-md border border-slate-200 bg-white p-2.5"
                                >
                                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-indigo-50 text-[10px] font-medium text-indigo-600">
                                    {index + 1}
                                  </span>
                                  <p className="line-clamp-3 text-xs leading-5 text-slate-600">
                                    {evidenceItemText(item)}
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()
            )}
          </section>
          {suggestion && (
            <section
              aria-label="AI 回复建议操作"
              className="shrink-0 space-y-2 border-t border-indigo-100 bg-indigo-50/30 p-4"
            >
              {suggestion.status === "completed" &&
                (() => {
                  const risk = suggestion.resolution?.risk;
                  return (
                    <>
                      {risk === "medium" && (
                        <label className="flex items-start gap-2 rounded-md border border-amber-200 bg-white p-2.5 text-xs text-slate-600">
                          <input
                            type="checkbox"
                            checked={confirmedFacts}
                            onChange={(e) => setConfirmedFacts(e.target.checked)}
                            className="mt-0.5 h-3.5 w-3.5 rounded accent-indigo-600"
                          />
                          <span>我已核对事实与规则</span>
                        </label>
                      )}
                      {risk === "high" && (
                        <p className="flex items-start gap-1.5 rounded-md border border-rose-200 bg-rose-50 p-2.5 text-xs leading-5 text-rose-700">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                          高风险建议必须升级主管处理
                        </p>
                      )}
                      <Button
                        className="w-full"
                        disabled={
                          sendingReply ||
                          risk === "high" ||
                          (risk === "medium" && !confirmedFacts)
                        }
                        onClick={() =>
                          void runCaseAction(
                            setSendingReply,
                            () =>
                              decideSupportSuggestion(
                                detail!.id,
                                suggestion.id,
                                edited === suggestion.content ? "accepted" : "edited",
                                edited,
                                undefined,
                                confirmedFacts
                              ),
                            "回复已审核并记录"
                          )
                        }
                      >
                        <Check className="mr-2 h-4 w-4" />
                        {edited === suggestion.content ? "采纳并发送" : "发送修订版"}
                      </Button>
                    </>
                  );
                })()}
              <Button
                variant="outline"
                className={cn(
                  "w-full border-indigo-200 bg-white text-indigo-600 hover:bg-indigo-50",
                  suggestion.resolution?.risk === "high" &&
                    "border-rose-300 bg-rose-600 text-white hover:bg-rose-700"
                )}
                disabled={escalating}
                onClick={() =>
                  void runCaseAction(
                    setEscalating,
                    () =>
                      raiseSupportEscalation(detail!.id, {
                        category: suggestion.riskFlags?.includes("food_safety")
                          ? "food_safety"
                          : suggestion.riskFlags?.includes("refund_review")
                            ? "refund_exception"
                            : suggestion.status === "insufficient_evidence"
                              ? "agent_insufficient_evidence"
                              : "customer_complaint",
                        reason:
                          "需要主管确认高风险处置：" + (suggestion.content || "").slice(0, 120),
                        riskLevel: suggestion.resolution?.risk === "high" ? "high" : "medium",
                        aiDiagnosis: suggestion.resolution
                          ? {
                              intent: suggestion.resolution.intent,
                              risk: suggestion.resolution.risk,
                              terminalState: suggestion.terminalState,
                              missingFacts: suggestion.resolution.missingFacts
                            }
                          : undefined
                      }),
                    "已升级主管"
                  )
                }
              >
                <ArrowUpRight className="mr-2 h-4 w-4" />
                升级主管
              </Button>
            </section>
          )}
        </aside>
      </section>
    </div>
  );
}
