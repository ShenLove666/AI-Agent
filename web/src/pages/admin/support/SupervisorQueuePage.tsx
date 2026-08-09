import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Check,
  FileWarning,
  Loader2,
  ShieldAlert,
  UserRoundCheck,
  type LucideIcon
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  acceptEscalation,
  getEscalationOverview,
  getEscalationQueue,
  resolveEscalation,
  returnEscalation,
  type EscalationOverview,
  type SupportEscalation
} from "@/services/supportService";

const CATEGORY_LABELS: Record<string, string> = {
  policy_uncertain: "政策不明确",
  refund_exception: "退款例外",
  food_safety: "食品安全",
  payment_risk: "支付风险",
  customer_complaint: "顾客投诉",
  compensation_request: "赔偿要求",
  agent_insufficient_evidence: "AI 证据不足",
  sla_timeout: "超时未处理"
};

const RISK_META: Record<string, { label: string; cls: string; icon: LucideIcon }> = {
  high: { label: "高风险", cls: "bg-red-50 text-red-700 border-red-200", icon: AlertTriangle },
  medium: {
    label: "中风险",
    cls: "bg-amber-50 text-amber-700 border-amber-200",
    icon: ShieldAlert
  },
  low: { label: "低风险", cls: "bg-slate-50 text-slate-600 border-slate-200", icon: BadgeCheck }
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  accepted: "已接管",
  returned: "已退回",
  transferred: "已转交",
  resolved: "已解决"
};

const STATUS_CLS: Record<string, string> = {
  pending: "bg-blue-50 text-blue-700",
  accepted: "bg-indigo-50 text-indigo-700",
  returned: "bg-slate-100 text-slate-600",
  transferred: "bg-sky-50 text-sky-700",
  resolved: "bg-emerald-50 text-emerald-700"
};

function slaLabel(raisedAt: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(raisedAt).getTime()) / 60000));
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  return hours >= 24 ? `${Math.floor(hours / 24)} 天前` : `${hours} 小时`;
}

export function SupervisorQueuePage() {
  const [items, setItems] = useState<SupportEscalation[]>([]);
  const [overview, setOverview] = useState<EscalationOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<"" | "pending" | "resolved" | "returned">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const load = async () => {
    try {
      const [queue, stats] = await Promise.all([getEscalationQueue(), getEscalationOverview()]);
      setItems(queue);
      setOverview(stats);
    } catch (error) {
      toast.error((error as Error).message || "加载升级队列失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(
    () => (filter ? items.filter((item) => item.status === filter) : items),
    [items, filter]
  );

  const selected = useMemo(
    () => filtered.find((item) => item.id === selectedId) || filtered[0] || null,
    [filtered, selectedId]
  );

  const handleAction = async (escalationId: number, action: string, actionNote?: string) => {
    setBusy(String(escalationId));
    try {
      if (action === "__accept__") {
        await acceptEscalation(escalationId);
        toast.success("已接管该升级");
      } else if (action === "__return__") {
        await returnEscalation(escalationId, actionNote);
        toast.success("已退回客服继续处理");
      } else {
        await resolveEscalation(escalationId, action, actionNote);
        toast.success("处理决议已记录");
      }
      setNote("");
      await load();
    } catch (error) {
      toast.error((error as Error).message || "操作失败");
    } finally {
      setBusy(null);
    }
  };

  const statCards = [
    { label: "待处理升级", value: overview?.pending ?? "--", cls: "bg-amber-400" },
    { label: "已接管", value: overview?.accepted ?? "--", cls: "bg-blue-400" },
    { label: "高风险", value: overview?.highRisk ?? "--", cls: "bg-red-400" },
    { label: "已解决", value: overview?.resolved ?? "--", cls: "bg-emerald-400" }
  ];

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在加载主管队列...
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1680px] space-y-4 pb-8">
      <section className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">主管工作台</h1>
            {overview?.highRisk ? (
              <Badge variant="destructive" className="font-normal">
                有 {overview.highRisk} 个高风险升级待处理
              </Badge>
            ) : null}
          </div>
          <p className="text-sm text-slate-500">
            处理普通客服升级的复杂问题、风险决策与例外处置，处理结果同步回工单。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          {statCards.map((card) => (
            <div key={card.label} className="flex items-center gap-1.5">
              <span className={cn("h-1.5 w-1.5 rounded-full", card.cls)} />
              <span className="text-xs text-slate-500">{card.label}</span>
              <span className="text-sm font-semibold text-slate-900">{card.value}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="flex items-center gap-1 rounded-md border border-slate-200 bg-white p-1">
        {(
          [
            ["", "全部"],
            ["pending", "待处理"],
            ["resolved", "已解决"],
            ["returned", "已退回"]
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => {
              setFilter(value);
              setSelectedId(null);
            }}
            className={cn(
              "rounded px-3 py-1.5 text-xs font-medium transition-colors",
              filter === value
                ? "bg-indigo-50 text-indigo-700"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white py-16 text-center">
          <ShieldAlert className="mb-3 h-8 w-8 text-slate-300" />
          <p className="text-sm text-slate-500">
            {filter ? "该状态暂无升级记录" : "没有待处理的升级，客服工作正常"}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
          {/* 左：高密度升级队列 */}
          <section aria-label="升级队列" className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="max-h-[70vh] overflow-y-auto">
              {filtered.map((item) => {
                const risk = RISK_META[item.riskLevel] || RISK_META.medium;
                const active = selected?.id === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedId(item.id)}
                    className={cn(
                      "w-full border-b border-slate-100 px-4 py-3 text-left transition hover:bg-slate-50",
                      active && "bg-indigo-50 shadow-[inset_2px_0_0_#4F46E5]",
                      !active && item.riskLevel === "high" && "shadow-[inset_2px_0_0_#f87171]"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-[13px] font-semibold text-slate-900">
                        {item.case?.subject || `工单 #${item.caseId}`}
                      </p>
                      <span
                        className={cn(
                          "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                          risk.cls
                        )}
                      >
                        <risk.icon className="h-3 w-3" />
                        {risk.label}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-slate-500">
                      {item.case?.customerName || "顾客"} · {item.case?.caseKey || `CASE-${item.caseId}`}
                    </p>
                    <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
                      <span>{CATEGORY_LABELS[item.category] || item.category}</span>
                      <span>·</span>
                      <span>{slaLabel(item.raisedAt)}</span>
                      <span
                        className={cn(
                          "ml-auto rounded-full px-2 py-0.5 font-medium",
                          STATUS_CLS[item.status] || "bg-slate-100 text-slate-600"
                        )}
                      >
                        {STATUS_LABELS[item.status] || item.status}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* 右：升级详情面板 */}
          {selected ? (
            <section
              aria-label="升级详情"
              className="flex h-fit max-h-[70vh] flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-5"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold text-slate-900">
                    {selected.case?.subject || `工单 #${selected.caseId}`}
                  </h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {selected.case?.customerName || "顾客"} ·{" "}
                    {selected.case?.caseKey || `CASE-${selected.caseId}`} · 升级于{" "}
                    {selected.raisedAt.slice(0, 16).replace("T", " ")}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      RISK_META[selected.riskLevel]?.cls || RISK_META.medium.cls
                    )}
                  >
                    {(() => {
                      const RiskIcon = RISK_META[selected.riskLevel]?.icon || ShieldAlert;
                      return <RiskIcon className="h-3 w-3" />;
                    })()}
                    {RISK_META[selected.riskLevel]?.label || "中风险"}
                  </span>
                  <Badge variant="outline">
                    {CATEGORY_LABELS[selected.category] || selected.category}
                  </Badge>
                </div>
              </div>

              <div className="mt-4 space-y-4">
                <div>
                  <p className="text-xs font-semibold text-slate-500">升级原因</p>
                  <p className="mt-1 text-sm leading-6 text-slate-700">{selected.reason}</p>
                </div>

                {selected.aiDiagnosis && Object.keys(selected.aiDiagnosis).length > 0 ? (
                  <div className="rounded-md border border-indigo-100 bg-indigo-50/50 p-3.5">
                    <p className="flex items-center gap-1.5 text-xs font-semibold text-indigo-600">
                      <FileWarning className="h-3.5 w-3.5" />
                      AI 风险诊断
                      <span className="rounded-full border border-indigo-200 bg-white px-1.5 py-px text-[10px] font-medium text-indigo-600">
                        AI
                      </span>
                    </p>
                    <div className="mt-2.5 flex flex-wrap gap-2 text-[11px]">
                      {selected.aiDiagnosis.intent ? (
                        <span className="rounded bg-white px-2 py-1 text-slate-600">
                          intent: {String(selected.aiDiagnosis.intent)}
                        </span>
                      ) : null}
                      {selected.aiDiagnosis.risk ? (
                        <span className="rounded bg-white px-2 py-1 text-slate-600">
                          risk: {String(selected.aiDiagnosis.risk)}
                        </span>
                      ) : null}
                      {selected.aiDiagnosis.terminalState ? (
                        <span className="rounded bg-white px-2 py-1 text-slate-600">
                          terminal: {String(selected.aiDiagnosis.terminalState)}
                        </span>
                      ) : null}
                      {Array.isArray(selected.aiDiagnosis.missingFacts) &&
                      selected.aiDiagnosis.missingFacts.length > 0 ? (
                        <span className="rounded bg-amber-50 px-2 py-1 text-amber-700">
                          缺失: {selected.aiDiagnosis.missingFacts.join("、")}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {selected.status === "pending" || selected.status === "accepted" ? (
                  <div className="space-y-3 border-t border-slate-100 pt-4">
                    <Textarea
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="处理备注（可选）"
                      className="min-h-[64px] resize-none text-sm"
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        disabled={busy === String(selected.id)}
                        onClick={() => handleAction(selected.id, "approved_refund", note || "批准退款处理")}
                      >
                        <Check className="mr-1 h-3.5 w-3.5" />
                        批准退款
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === String(selected.id)}
                        onClick={() =>
                          handleAction(selected.id, "approved_compensation", note || "批准补偿方案")
                        }
                      >
                        <BadgeCheck className="mr-1 h-3.5 w-3.5" />
                        批准补偿
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="text-amber-700"
                        disabled={busy === String(selected.id)}
                        onClick={() =>
                          handleAction(selected.id, "request_more_evidence", note || "要求补充材料")
                        }
                      >
                        <FileWarning className="mr-1 h-3.5 w-3.5" />
                        要求补充材料
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === String(selected.id)}
                        onClick={() =>
                          handleAction(selected.id, "transfer_specialist", note || "转食品安全专员")
                        }
                      >
                        <ArrowRight className="mr-1 h-3.5 w-3.5" />
                        转专员
                      </Button>
                      {selected.status === "pending" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy === String(selected.id)}
                          onClick={() => handleAction(selected.id, "__accept__", note)}
                        >
                          <UserRoundCheck className="mr-1 h-3.5 w-3.5" />
                          接管
                        </Button>
                      ) : null}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-slate-500"
                        disabled={busy === String(selected.id)}
                        onClick={() => handleAction(selected.id, "__return__", note || "退回客服继续处理")}
                      >
                        <ArrowLeft className="mr-1 h-3.5 w-3.5" />
                        退回客服
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    {selected.resolutionNote ||
                      (selected.resolution ? `处理决议：${selected.resolution}` : "已处理")}
                  </div>
                )}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
