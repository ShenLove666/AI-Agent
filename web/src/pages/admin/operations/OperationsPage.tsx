import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  Download,
  RefreshCw,
  Store,
  Target,
  ThumbsUp,
  Users
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  getOperationsOverview,
  type OperationsOverview
} from "@/services/dashboardService";

type WindowValue = "24h" | "7d" | "30d";

const WINDOWS: Array<{ value: WindowValue; label: string }> = [
  { value: "24h", label: "近 24 小时" },
  { value: "7d", label: "近 7 天" },
  { value: "30d", label: "近 30 天" }
];

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value || 0);
}

function exportReport(data: OperationsOverview) {
  const rows: Array<Array<string | number>> = [
    ["商家 AI 运营洞察报告", data.window],
    ["指标", "数值"],
    ["商家账号", data.kpis.merchantAccounts],
    ["活跃商家", data.kpis.activeMerchants],
    ["工具渗透率", `${data.kpis.penetrationRate}%`],
    ["AI 回答量", data.kpis.aiResponses],
    ["反馈覆盖率", `${data.kpis.feedbackCoverage}%`],
    ["回答好评率", `${data.kpis.positiveRate}%`],
    ["知识命中率", `${data.kpis.knowledgeHitRate}%`],
    [],
    ["高频意图", "咨询量", "占比"],
    ...data.intentDistribution.map((item) => [item.name, item.count, `${item.rate}%`]),
    [],
    ["问题", "数量", "问题率", "优先级", "建议动作"],
    ...data.issues.map((item) => [item.name, item.count, `${item.rate}%`, item.priority, item.action])
  ];
  const csv = rows
    .map((row) => row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `商家AI运营洞察-${data.window}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function MetricCard({
  label,
  value,
  suffix,
  note,
  icon: Icon,
  tone = "indigo"
}: {
  label: string;
  value: number;
  suffix?: string;
  note: string;
  icon: typeof Store;
  tone?: "indigo" | "emerald" | "amber";
}) {
  const colors = {
    indigo: "bg-indigo-50 text-indigo-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600"
  };
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-500">{label}</p>
          <p className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">
            {suffix ? value.toFixed(1) : formatNumber(value)}
            {suffix && <span className="ml-1 text-base font-medium text-slate-500">{suffix}</span>}
          </p>
        </div>
        <span className={cn("rounded-xl p-2.5", colors[tone])}>
          <Icon className="h-5 w-5" />
        </span>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500">{note}</p>
    </article>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-5 text-center">
      <BarChart3 className="mb-3 h-7 w-7 text-slate-300" />
      <p className="text-sm font-medium text-slate-600">{text}</p>
      <p className="mt-1 text-xs text-slate-400">产生真实会话和反馈后，这里会自动更新</p>
    </div>
  );
}

export function OperationsPage() {
  const [windowValue, setWindowValue] = useState<WindowValue>("7d");
  const [data, setData] = useState<OperationsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getOperationsOverview(windowValue));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运营数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [windowValue]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxIntent = useMemo(
    () => Math.max(...(data?.intentDistribution.map((item) => item.count) ?? [0]), 1),
    [data]
  );

  if (loading && !data) {
    return (
      <div className="space-y-5 p-1">
        <div className="h-28 animate-pulse rounded-lg bg-slate-100" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-36 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      <section className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="rounded-md border border-indigo-100 bg-indigo-50 p-1 text-indigo-600">
              <Activity className="h-4 w-4" />
            </span>
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              商家 AI 产品运营工作台
            </span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            从工具使用到 Agent 优化的业务闭环
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
            追踪商家渗透、回答质量和问题瓶颈，用真实反馈与运行链路支持知识库、提示词和模型路由迭代。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-slate-200 bg-white p-0.5">
            {WINDOWS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setWindowValue(item.value)}
                className={cn(
                  "rounded px-3 py-1.5 text-xs font-medium transition",
                  windowValue === item.value
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-500 hover:bg-slate-50"
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />刷新
          </Button>
          <Button
            onClick={() => {
              if (!data) return;
              exportReport(data);
              toast.success("运营洞察报告已导出");
            }}
            disabled={!data}
          >
            <Download className="mr-2 h-4 w-4" />导出报告
          </Button>
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <AlertTriangle className="h-4 w-4" />{error}
        </div>
      )}

      {data && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="活跃商家" value={data.kpis.activeMerchants} note={`共 ${formatNumber(data.kpis.merchantAccounts)} 个商家账号`} icon={Store} />
            <MetricCard label="AI 工具渗透率" value={data.kpis.penetrationRate} suffix="%" note="窗口内使用 AI 的商家 / 全部商家" icon={Target} tone="emerald" />
            <MetricCard label="AI 回答量" value={data.kpis.aiResponses} note="用于衡量真实使用规模与运营触达" icon={Bot} />
            <MetricCard label="反馈覆盖率" value={data.kpis.feedbackCoverage} suffix="%" note={`已标注 ${formatNumber(data.quality.evaluated)} 条回答`} icon={Users} tone="amber" />
            <MetricCard label="回答好评率" value={data.kpis.positiveRate} suffix="%" note={`${formatNumber(data.quality.positive)} 赞 / ${formatNumber(data.quality.negative)} 踩`} icon={ThumbsUp} tone="emerald" />
            <MetricCard label="知识命中率" value={data.kpis.knowledgeHitRate} suffix="%" note="基于检索节点有无返回文档计算" icon={CheckCircle2} tone="emerald" />
          </section>

          <section className="grid gap-5 xl:grid-cols-[1.08fr_0.92fr]">
            <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-5 flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-slate-900">商家需求意图分布</h2>
                  <p className="mt-1 text-xs text-slate-500">识别高频经营诉求，为知识补齐和产品迭代排优先级</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">规则基线</span>
              </div>
              {data.intentDistribution.length === 0 ? (
                <EmptyState text="暂无商家咨询数据" />
              ) : (
                <div className="space-y-4">
                  {data.intentDistribution.map((item) => (
                    <div key={item.name}>
                      <div className="mb-1.5 flex items-center justify-between text-sm">
                        <span className="font-medium text-slate-700">{item.name}</span>
                        <span className="text-slate-500">{formatNumber(item.count)} · {item.rate.toFixed(1)}%</span>
                      </div>
                      <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-indigo-500 transition-all"
                          style={{ width: `${Math.max((item.count / maxIntent) * 100, 3)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-slate-900">Agent 质量评测漏斗</h2>
              <p className="mt-1 text-xs text-slate-500">把线上反馈转化为可持续优化的标注资产</p>
              <div className="mt-6 space-y-3">
                {[
                  { label: "完成运行", value: data.quality.traceRuns, width: 100, className: "bg-indigo-600" },
                  { label: "收到反馈", value: data.quality.evaluated, width: data.quality.traceRuns ? data.quality.evaluated / data.quality.traceRuns * 100 : 0, className: "bg-violet-500" },
                  { label: "正向回答", value: data.quality.positive, width: data.quality.traceRuns ? data.quality.positive / data.quality.traceRuns * 100 : 0, className: "bg-emerald-500" },
                  { label: "待复盘样本", value: data.quality.negative, width: data.quality.traceRuns ? data.quality.negative / data.quality.traceRuns * 100 : 0, className: "bg-amber-500" }
                ].map((item) => (
                  <div key={item.label} className="rounded-xl bg-slate-50 p-3">
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <span className="text-slate-600">{item.label}</span>
                      <strong className="text-slate-900">{formatNumber(item.value)}</strong>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div className={cn("h-full rounded-full", item.className)} style={{ width: `${Math.min(Math.max(item.width, item.value ? 4 : 0), 100)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 px-5 py-4">
              <h2 className="font-semibold text-slate-900">问题诊断与运营动作</h2>
              <p className="mt-1 text-xs text-slate-500">从数据发现瓶颈，并明确下一步负责人可执行的优化方向</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-5 py-3">问题类型</th><th className="px-5 py-3">样本数</th><th className="px-5 py-3">问题率</th><th className="px-5 py-3">优先级</th><th className="px-5 py-3">建议动作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.issues.map((issue) => (
                    <tr key={issue.name} className="hover:bg-slate-50/70">
                      <td className="px-5 py-4 font-medium text-slate-800">{issue.name}</td>
                      <td className="px-5 py-4 text-slate-600">{formatNumber(issue.count)}</td>
                      <td className="px-5 py-4 text-slate-600">{issue.rate.toFixed(1)}%</td>
                      <td className="px-5 py-4"><span className={cn("rounded-full px-2.5 py-1 text-xs font-medium", issue.priority === "高" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700")}>{issue.priority}</span></td>
                      <td className="px-5 py-4 text-slate-600">{issue.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <aside className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500">
            <strong className="text-slate-700">口径说明：</strong>{data.methodology.merchantProxy} {data.methodology.intentMethod} 慢响应阈值为 {data.methodology.slowThresholdMs / 1000} 秒。页面所有结果均由当前系统真实数据计算，无数据时显示 0。
          </aside>
        </>
      )}
    </div>
  );
}
