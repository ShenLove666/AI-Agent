import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  Check,
  CheckCircle2,
  FileText,
  Inbox,
  Loader2,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UserRoundCheck
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  assignSupportCase,
  decideSupportSuggestion,
  generateSupportSuggestion,
  getSupportCase,
  getSupportCases,
  getSupportMetrics,
  sendManualReply,
  transitionSupportCase,
  type CaseStatus,
  type SupportCaseDetail,
  type SupportCaseSummary,
  type SupportMetrics
} from "@/services/supportService";
import { useAuthStore } from "@/stores/authStore";

const statuses: Record<CaseStatus, string> = {
  pending: "待处理",
  in_progress: "处理中",
  resolved: "已解决",
  escalated: "已升级"
};
const priorities = { low: "低", normal: "普通", high: "高", urgent: "紧急" };
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
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{label}</p>
        <span className={cn("h-2.5 w-2.5 rounded-full", tone)} />
      </div>
      <strong className="mt-2 block text-2xl text-slate-950">{value}</strong>
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
        "w-full border-b border-slate-100 p-4 text-left transition hover:bg-slate-50",
        active && "bg-blue-50/70 shadow-[inset_3px_0_0_#3b82f6]"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {item.unread && <span className="h-2 w-2 rounded-full bg-blue-500" />}
            <p className="truncate text-sm font-semibold text-slate-900">{item.subject}</p>
          </div>
          <p className="mt-1 truncate text-xs text-slate-500">
            {item.customerName} · {item.lastMessage}
          </p>
        </div>
        <span className={cn("text-[11px] font-semibold", priorityTone[item.priority])}>
          {priorities[item.priority]}
        </span>
      </div>
      <div className="mt-3 flex items-center justify-between">
        <span
          className={cn("rounded-full px-2 py-1 text-[10px] font-medium", statusTone[item.status])}
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
  const [status, setStatus] = useState<string>("pending");
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState("");
  const [edited, setEdited] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const selectCase = useCallback(async (id: number) => {
    const value = await getSupportCase(id);
    setDetail(value);
    const suggestion = value.suggestions.find((x) => !x.decision);
    setEdited(suggestion?.content || "");
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [items, summary] = await Promise.all([
        getSupportCases({ status: status || undefined, search: search || undefined }),
        getSupportMetrics()
      ]);
      setCases(items);
      setMetrics(summary);
      if (items.length) {
        const id = items.some((x) => x.id === detail?.id) ? detail!.id : items[0].id;
        await selectCase(id);
      } else setDetail(null);
    } catch (e) {
      toast.error((e as Error).message || "工单加载失败");
    } finally {
      setLoading(false);
    }
  }, [detail?.id, search, status, selectCase]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), search ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [search, status]); // eslint-disable-line react-hooks/exhaustive-deps
  const action = async (fn: () => Promise<SupportCaseDetail>, message: string) => {
    setBusy(true);
    try {
      const value = await fn();
      setDetail(value);
      setCases((list) => list.map((x) => (x.id === value.id ? value : x)));
      setMetrics(await getSupportMetrics());
      setEdited(value.suggestions.find((x) => !x.decision)?.content || "");
      toast.success(message);
    } catch (e) {
      toast.error((e as Error).message || "操作失败");
    } finally {
      setBusy(false);
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
          "bg-blue-500"
        ],
        [
          "解决率",
          metrics?.resolutionRate == null ? "--" : `${metrics.resolutionRate}%`,
          "来自真实状态事件",
          "bg-emerald-500"
        ],
        [
          "AI 采纳率",
          metrics?.acceptanceRate == null ? "--" : `${metrics.acceptanceRate}%`,
          "含人工修订发送",
          "bg-violet-500"
        ],
        [
          "引用覆盖",
          metrics?.citationCoverage == null ? "--" : `${metrics.citationCoverage}%`,
          "已生成建议",
          "bg-amber-500"
        ]
      ] as const,
    [metrics]
  );
  return (
    <div className="mx-auto max-w-[1680px] space-y-5 pb-8">
      <section className="flex flex-col justify-between gap-4 rounded-[28px] border border-blue-100 bg-gradient-to-r from-white via-blue-50/70 to-indigo-50 p-6 md:flex-row md:items-center">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <Badge className="bg-blue-600 hover:bg-blue-600">AI 客服质检闭环</Badge>
            {metrics?.provenance === "demo" && (
              <span className="text-xs text-slate-500">演示数据 · 指标由工单事件计算</span>
            )}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">客服工作台</h1>
          <p className="mt-2 text-sm text-slate-600">
            处理顾客问题、审核 AI 回复，并把失败案例沉淀为知识改进任务。
          </p>
        </div>
        <Button variant="outline" className="gap-2 bg-white" onClick={() => void load()}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          刷新
        </Button>
      </section>
      <section className="grid gap-3 md:grid-cols-4">
        {cards.map(([a, b, c, d]) => (
          <Metric key={a} label={a} value={b} caption={c} tone={d} />
        ))}
      </section>
      <section className="grid min-h-[680px] overflow-hidden rounded-[24px] border border-slate-200 bg-white shadow-xl shadow-slate-200/40 xl:grid-cols-[330px_minmax(420px,1fr)_390px]">
        <aside className="border-r border-slate-200 bg-white">
          <div className="border-b border-slate-200 p-4">
            <div className="flex items-center gap-2">
              <Inbox className="h-5 w-5 text-blue-600" />
              <h2 className="font-semibold">工单队列</h2>
              <span className="rounded-full bg-slate-100 px-2 text-xs text-slate-500">
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
          <div className="max-h-[545px] overflow-auto">
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
        <main className="flex min-w-0 flex-col bg-slate-50/40">
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
                      disabled={busy || !user?.id}
                      onClick={() =>
                        user?.id &&
                        void action(
                          () => assignSupportCase(detail.id, user.id, detail.version),
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
                      disabled={busy}
                      onClick={() =>
                        void action(
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
              <div className="flex-1 space-y-5 overflow-auto p-5">
                {detail.provenance?.dataSource && (
                  <section
                    className="rounded-2xl border border-blue-200 bg-blue-50/70 p-4"
                    aria-label="案例数据来源"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                          案例数据来源
                        </p>
                        <h3 className="mt-1 text-sm font-semibold text-slate-900">
                          {detail.provenance.dataSource.title}
                        </h3>
                        <p className="mt-1 text-xs text-slate-500">
                          记录 {detail.provenance.sourceRecordKey} · 生成器{" "}
                          {detail.provenance.generatorVersion}
                        </p>
                      </div>
                      <Badge className="bg-blue-600 hover:bg-blue-600">来源关联演示</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {Object.entries(detail.provenance.fieldLineage).map(([field, lineage]) => (
                        <span
                          key={field}
                          className={cn(
                            "rounded-full px-2 py-1 text-[11px]",
                            lineage.provenance === "observed"
                              ? "bg-emerald-100 text-emerald-700"
                              : lineage.provenance === "derived"
                                ? "bg-violet-100 text-violet-700"
                                : "bg-amber-100 text-amber-700"
                          )}
                        >
                          {field}: {lineage.provenance}
                        </span>
                      ))}
                    </div>
                    <p className="mt-3 text-[11px] leading-5 text-slate-500">
                      观测数据只提供购物篮与商品；顾客表述、工单状态和处理结果是确定性 synthetic
                      场景，不代表真实顾客或业务效果。
                    </p>
                  </section>
                )}
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
                          "rounded-2xl px-4 py-3 text-left text-sm leading-6 shadow-sm",
                          message.role === "agent"
                            ? "rounded-tr-sm bg-blue-600 text-white"
                            : "rounded-tl-sm border border-slate-200 bg-white text-slate-700"
                        )}
                      >
                        {message.content}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="m-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <Textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="输入人工回复，或使用右侧 AI 建议…"
                  className="min-h-[76px] resize-none border-0 p-0 shadow-none focus-visible:ring-0"
                />
                <div className="flex justify-end border-t pt-3">
                  <Button
                    size="sm"
                    disabled={busy || !draft.trim()}
                    onClick={() =>
                      void action(async () => {
                        const value = await sendManualReply(detail.id, draft);
                        setDraft("");
                        return value;
                      }, "回复已记录")
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
        <aside className="border-l border-slate-200 bg-white">
          <header className="flex items-center justify-between border-b border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <span className="rounded-xl bg-violet-100 p-2 text-violet-600">
                <Sparkles className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">AI 回复建议</h2>
                <p className="text-[11px] text-slate-400">已发布知识 · 人工审核</p>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !detail}
              onClick={async () => {
                if (!detail) return;
                setBusy(true);
                try {
                  await generateSupportSuggestion(detail.id);
                  await selectCase(detail.id);
                  toast.success("建议生成完成");
                } catch (e) {
                  toast.error((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-3.5 w-3.5" />
              )}
              生成
            </Button>
          </header>
          <div className="p-5">
            {!suggestion ? (
              <div className="py-20 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-50 text-violet-600">
                  <Sparkles />
                </div>
                <h3 className="mt-4 font-semibold">先查规则，再拟回复</h3>
                <p className="mx-auto mt-2 max-w-[260px] text-xs leading-5 text-slate-500">
                  只引用当前已发布知识；资料不足会明确提示，不把猜测包装成答案。
                </p>
              </div>
            ) : suggestion.status !== "completed" ? (
              <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
                <AlertTriangle className="h-5 w-5 text-amber-600" />
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
              <div className="space-y-4">
                {suggestion.riskFlags.length > 0 && (
                  <div className="flex gap-2 rounded-xl bg-rose-50 p-3 text-xs text-rose-700">
                    <ShieldCheck className="h-4 w-4 shrink-0" />
                    检测到退款、支付或安全风险，发送前必须人工确认
                  </div>
                )}
                <Textarea
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                  className="min-h-[150px] resize-none leading-6"
                />
                <div>
                  <p className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-500">
                    <FileText className="h-4 w-4" />
                    引用证据 · {suggestion.citations.length}
                  </p>
                  {suggestion.citations.map((citation, index) => (
                    <div
                      key={index}
                      className="mb-2 flex gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-blue-100 text-[10px] text-blue-700">
                        {index + 1}
                      </span>
                      <p className="line-clamp-3 text-xs leading-5 text-slate-600">
                        {citation.content ||
                          citation.title ||
                          `发布版本 ${citation.releaseVersion}`}
                      </p>
                    </div>
                  ))}
                </div>
                <Button
                  className="w-full"
                  disabled={busy}
                  onClick={() =>
                    void action(
                      () =>
                        decideSupportSuggestion(
                          detail!.id,
                          suggestion.id,
                          edited === suggestion.content ? "accepted" : "edited",
                          edited
                        ),
                      "回复已审核并记录"
                    )
                  }
                >
                  <Check className="mr-2 h-4 w-4" />
                  {edited === suggestion.content ? "采纳并发送" : "发送修订版"}
                </Button>
                <Button
                  variant="outline"
                  className="w-full border-amber-200 text-amber-700"
                  disabled={busy}
                  onClick={() =>
                    void action(
                      () =>
                        decideSupportSuggestion(
                          detail!.id,
                          suggestion.id,
                          "escalated",
                          undefined,
                          "需要主管确认高风险处置"
                        ),
                      "已升级主管"
                    )
                  }
                >
                  <ArrowUpRight className="mr-2 h-4 w-4" />
                  升级主管
                </Button>
                <p className="text-center text-[10px] text-slate-400">
                  {suggestion.modelId} · {suggestion.promptVersion} · {suggestion.latencyMs}ms
                </p>
              </div>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
