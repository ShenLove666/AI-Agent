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

function EscalationCard({
  item,
  busy,
  onAction
}: {
  item: SupportEscalation;
  busy: string | null;
  onAction: (escalationId: number, action: string, note?: string) => void;
}) {
  const [note, setNote] = useState("");
  const risk = RISK_META[item.riskLevel] || RISK_META.medium;
  const RiskIcon = risk.icon;

  return (
    <article className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-4">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium",
              risk.cls
            )}
          >
            <RiskIcon className="h-3 w-3" />
            {risk.label}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">
              {item.case?.subject || `工单 #${item.caseId}`}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              {item.case?.customerName || "顾客"} · {item.case?.caseKey || `CASE-${item.caseId}`} ·{" "}
              升级 {item.raisedAt.slice(0, 16).replace("T", " ")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{CATEGORY_LABELS[item.category] || item.category}</Badge>
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-[11px] font-medium",
              item.status === "resolved"
                ? "bg-emerald-50 text-emerald-700"
                : item.status === "returned"
                  ? "bg-slate-100 text-slate-600"
                  : "bg-blue-50 text-blue-700"
            )}
          >
            {STATUS_LABELS[item.status] || item.status}
          </span>
        </div>
      </div>

      <div className="space-y-3 p-4">
        <div>
          <p className="text-xs font-semibold text-slate-500">升级原因</p>
          <p className="mt-1 text-sm leading-6 text-slate-700">{item.reason}</p>
        </div>

        {item.aiDiagnosis && Object.keys(item.aiDiagnosis).length > 0 ? (
          <div className="rounded-xl border border-violet-100 bg-violet-50/50 p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-violet-700">
              <FileWarning className="h-3.5 w-3.5" />
              AI 风险诊断
            </p>
            <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
              {item.aiDiagnosis.intent ? (
                <span className="rounded-md bg-white px-2 py-1 text-slate-600">
                  intent: {String(item.aiDiagnosis.intent)}
                </span>
              ) : null}
              {item.aiDiagnosis.risk ? (
                <span className="rounded-md bg-white px-2 py-1 text-slate-600">
                  risk: {String(item.aiDiagnosis.risk)}
                </span>
              ) : null}
              {item.aiDiagnosis.terminalState ? (
                <span className="rounded-md bg-white px-2 py-1 text-slate-600">
                  terminal: {String(item.aiDiagnosis.terminalState)}
                </span>
              ) : null}
              {Array.isArray(item.aiDiagnosis.missingFacts) &&
              item.aiDiagnosis.missingFacts.length > 0 ? (
                <span className="rounded-md bg-amber-50 px-2 py-1 text-amber-700">
                  缺失: {item.aiDiagnosis.missingFacts.join("、")}
                </span>
              ) : null}
            </div>
          </div>
        ) : null}

        {item.status === "pending" || item.status === "accepted" ? (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <Textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="处理备注（可选）"
              className="min-h-[64px] resize-none text-sm"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                className="bg-emerald-600 hover:bg-emerald-700"
                disabled={busy === String(item.id)}
                onClick={() => onAction(item.id, "approved_refund", note || "批准退款处理")}
              >
                <Check className="mr-1 h-3.5 w-3.5" />
                批准退款
              </Button>
              <Button
                size="sm"
                className="bg-violet-600 hover:bg-violet-700"
                disabled={busy === String(item.id)}
                onClick={() => onAction(item.id, "approved_compensation", note || "批准补偿方案")}
              >
                <BadgeCheck className="mr-1 h-3.5 w-3.5" />
                批准补偿
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="border-amber-200 text-amber-700"
                disabled={busy === String(item.id)}
                onClick={() => onAction(item.id, "request_more_evidence", note || "要求补充材料")}
              >
                <FileWarning className="mr-1 h-3.5 w-3.5" />
                要求补充材料
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="border-sky-200 text-sky-700"
                disabled={busy === String(item.id)}
                onClick={() => onAction(item.id, "transfer_specialist", note || "转食品安全专员")}
              >
                <ArrowRight className="mr-1 h-3.5 w-3.5" />
                转专员
              </Button>
              {item.status === "pending" ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy === String(item.id)}
                  onClick={() => onAction(item.id, "__accept__", note)}
                >
                  <UserRoundCheck className="mr-1 h-3.5 w-3.5" />
                  接管
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                className="text-slate-500"
                disabled={busy === String(item.id)}
                onClick={() => onAction(item.id, "__return__", note || "退回客服继续处理")}
              >
                <ArrowLeft className="mr-1 h-3.5 w-3.5" />
                退回客服
              </Button>
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            {item.resolutionNote || (item.resolution ? `处理决议：${item.resolution}` : "已处理")}
          </div>
        )}
      </div>
    </article>
  );
}

export function SupervisorQueuePage() {
  const [items, setItems] = useState<SupportEscalation[]>([]);
  const [overview, setOverview] = useState<EscalationOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<"" | "pending" | "resolved" | "returned">("");

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

  const handleAction = async (escalationId: number, action: string, note?: string) => {
    setBusy(String(escalationId));
    try {
      if (action === "__accept__") {
        await acceptEscalation(escalationId);
        toast.success("已接管该升级");
      } else if (action === "__return__") {
        await returnEscalation(escalationId, note);
        toast.success("已退回客服继续处理");
      } else {
        await resolveEscalation(escalationId, action, note);
        toast.success("处理决议已记录");
      }
      await load();
    } catch (error) {
      toast.error((error as Error).message || "操作失败");
    } finally {
      setBusy(null);
    }
  };

  const statCards = [
    { label: "待处理升级", value: overview?.pending ?? "--", cls: "bg-amber-50 text-amber-700" },
    { label: "已接管", value: overview?.accepted ?? "--", cls: "bg-blue-50 text-blue-700" },
    { label: "高风险", value: overview?.highRisk ?? "--", cls: "bg-red-50 text-red-700" },
    { label: "已解决", value: overview?.resolved ?? "--", cls: "bg-emerald-50 text-emerald-700" }
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
    <div className="mx-auto max-w-[1680px] space-y-5 pb-8">
      <section className="rounded-[28px] border border-amber-100 bg-gradient-to-r from-white via-amber-50/70 to-orange-50 p-6">
        <div className="mb-3 flex items-center gap-2">
          <Badge className="bg-amber-600 hover:bg-amber-600">主管队列</Badge>
          {overview?.highRisk ? (
            <span className="text-xs text-red-600">有 {overview.highRisk} 个高风险升级待处理</span>
          ) : null}
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">主管工作台</h1>
        <p className="mt-2 text-sm text-slate-600">
          处理普通客服升级的复杂问题、风险决策与例外处置，处理结果同步回工单。
        </p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {statCards.map((card) => (
            <div key={card.label} className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">{card.label}</p>
              <p className={cn("mt-1 text-2xl font-semibold", card.cls)}>{card.value}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="flex items-center gap-2">
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
            onClick={() => setFilter(value)}
            className={cn(
              "rounded-full px-4 py-1.5 text-xs font-medium transition-colors",
              filter === value
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 hover:bg-slate-100"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
          <ShieldAlert className="mb-3 h-8 w-8 text-slate-300" />
          <p className="text-sm text-slate-500">
            {filter ? "该状态暂无升级记录" : "没有待处理的升级，客服工作正常"}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {filtered.map((item) => (
            <EscalationCard key={item.id} item={item} busy={busy} onAction={handleAction} />
          ))}
        </div>
      )}
    </div>
  );
}
