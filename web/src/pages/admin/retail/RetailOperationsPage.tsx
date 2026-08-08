import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  BarChart3,
  Check,
  ClipboardCheck,
  Database,
  Download,
  RefreshCw,
  ShoppingBasket,
  Sparkles,
  Store,
  Target,
  TriangleAlert
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DataSourcesView } from "./DataSourcesView";
import {
  createRetailCampaign,
  getRetailOverview,
  getRetailReport,
  transitionRetailTask,
  type RetailOverview
} from "@/services/retailService";

const statusLabel: Record<string, string> = {
  draft: "待确认",
  published: "已发布",
  new: "待确认",
  confirmed: "已确认",
  optimizing: "优化中",
  pending_verification: "待复测",
  resolved: "已解决",
  completed: "已完成"
};
const nextStatus: Record<string, string> = {
  new: "confirmed",
  confirmed: "optimizing",
  optimizing: "pending_verification",
  pending_verification: "resolved"
};
const format = (value: number) => new Intl.NumberFormat("zh-CN").format(value);

function OriginBadge({ origin }: { origin: "observed" | "derived" | "synthetic" }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[11px] font-medium",
        origin === "observed"
          ? "bg-emerald-50 text-emerald-700"
          : origin === "derived"
            ? "bg-violet-50 text-violet-700"
            : "bg-amber-50 text-amber-700"
      )}
    >
      {origin === "observed"
        ? "真实观测数据"
        : origin === "derived"
          ? "可复算衍生指标"
          : "模拟运营数据"}
    </span>
  );
}

export function RetailOperationsPage() {
  const [data, setData] = useState<RetailOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const overview = await getRetailOverview();
      setData(overview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "运营数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const topLift = useMemo(() => data?.rules[0]?.lift ?? 0, [data]);

  const downloadReport = async () => {
    try {
      const report = await getRetailReport();
      const url = URL.createObjectURL(
        new Blob([report.content], { type: "text/markdown;charset=utf-8" })
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = report.filename;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success("运营周报已生成");
    } catch {
      /* interceptor shows message */
    }
  };

  if (loading && !data)
    return (
      <div className="space-y-4">
        <div className="h-48 animate-pulse rounded-3xl bg-slate-100" />
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-100" />
          ))}
        </div>
      </div>
    );

  if (!data || data.dataState === "empty")
    return (
      <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <ShoppingBasket className="mx-auto h-10 w-10 text-slate-300" />
        <h1 className="mt-4 text-xl font-semibold">还没有即时零售数据</h1>
        <p className="mt-2 text-sm text-slate-500">
          运行 seed-retail 命令导入购物篮后即可查看真实关联洞察。
        </p>
      </div>
    );

  return (
    <div className="space-y-6 pb-10">
      <section className="relative overflow-hidden rounded-3xl bg-[radial-gradient(circle_at_top_right,_#14b8a6_0,_#0f766e_24%,_#0f172a_70%)] p-7 text-white shadow-xl shadow-slate-200">
        <div className="relative z-10 flex flex-col justify-between gap-6 xl:flex-row xl:items-end">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-teal-200">
              <Sparkles className="h-4 w-4" />
              Instant Retail AI Operations
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight">{data.profile?.name}</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-200">
              从真实购物篮发现搭配机会，把运营方案发布到 AI 客服，再用评测、标注和优化任务验证效果。
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-full bg-white/10 px-3 py-1 text-xs">
                {data.profile?.businessType}
              </span>
              <span className="rounded-full bg-white/10 px-3 py-1 text-xs">
                {data.profile?.storeCount
                  ? `${data.profile.storeCount} 家门店`
                  : "源数据未提供门店维度"}
              </span>
              <OriginBadge origin="observed" />
              <OriginBadge origin="synthetic" />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white"
              onClick={() => void load()}
              disabled={loading}
            >
              <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />
              刷新
            </Button>
            <Button
              className="bg-white text-slate-900 hover:bg-teal-50"
              onClick={() => void downloadReport()}
            >
              <Download className="mr-2 h-4 w-4" />
              生成运营周报
            </Button>
          </div>
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <TriangleAlert className="h-4 w-4" />
          {error}
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          {
            label: "真实购物篮",
            value: format(data.summary!.orders),
            note: `${format(data.summary!.rows)} 条商品明细`,
            icon: ShoppingBasket
          },
          {
            label: "商品数量",
            value: format(data.summary!.products),
            note: "跨两份来源，分类口径不混合",
            icon: Database
          },
          {
            label: "平均篮子",
            value: data.summary!.averageBasketSize.toFixed(2),
            note: "件 / 单",
            icon: Store
          },
          {
            label: "可行动规则",
            value: format(data.summary!.rules),
            note: "已通过最小证据阈值",
            icon: Target
          },
          { label: "最高提升度", value: topLift.toFixed(2), note: "关联强度 Lift", icon: BarChart3 }
        ].map(({ label, value, note, icon: Icon }) => (
          <article
            key={label}
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-500">{label}</span>
              <span className="rounded-xl bg-teal-50 p-2 text-teal-700">
                <Icon className="h-4 w-4" />
              </span>
            </div>
            <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">{value}</p>
            <p className="mt-2 text-xs text-slate-400">{note}</p>
          </article>
        ))}
      </section>

      <DataSourcesView />

      <section className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-slate-900">商家接入清单</h2>
              <p className="mt-1 text-xs text-slate-500">上线准备状态与明确阻塞项</p>
            </div>
            <span
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium",
                data.ready ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
              )}
            >
              {data.ready ? "可进入运营" : "存在阻塞"}
            </span>
          </div>
          <div className="mt-5 space-y-3">
            {data.checklist?.map((item) => (
              <div
                key={item.key}
                className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      "grid h-7 w-7 place-items-center rounded-full",
                      item.done ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
                    )}
                  >
                    {item.done ? <Check className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
                  </span>
                  <span className="text-sm font-medium text-slate-700">{item.label}</span>
                </div>
                <span className="text-xs text-slate-400">
                  {item.optional ? "可选增强" : item.done ? "已完成" : "待处理"}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <h2 className="font-semibold text-slate-900">运营效果指标</h2>
            <p className="mt-1 text-xs text-slate-500">
              所有比例同时展示分子/分母；本区为确定性模拟事件
            </p>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {data.metrics.map((metric) => (
              <article
                key={metric.key}
                className="rounded-xl border border-slate-100 bg-slate-50/70 p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-600">{metric.label}</span>
                  <OriginBadge origin="synthetic" />
                </div>
                <p className="mt-2 text-2xl font-semibold text-slate-900">
                  {metric.value === null ? "数据不足" : `${metric.value}${metric.unit}`}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  证据口径 {metric.numerator} / {metric.denominator}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="font-semibold text-slate-900">高价值购物篮关联</h2>
            <p className="mt-1 text-xs text-slate-500">
              支持度、置信度和提升度全部由源购物篮计算，可下钻订单证据
            </p>
          </div>
          <OriginBadge origin="derived" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-5 py-3">关联建议</th>
                <th className="px-5 py-3">共现</th>
                <th className="px-5 py-3">支持度</th>
                <th className="px-5 py-3">置信度</th>
                <th className="px-5 py-3">提升度</th>
                <th className="px-5 py-3">证据</th>
                <th className="px-5 py-3">动作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.rules.slice(0, 10).map((rule) => (
                <tr key={rule.id} className="hover:bg-teal-50/30">
                  <td className="px-5 py-4 font-medium text-slate-800">
                    {rule.from}
                    <ArrowRight className="mx-2 inline h-4 w-4 text-teal-600" />
                    {rule.to}
                  </td>
                  <td className="px-5 py-4">{rule.count} 单</td>
                  <td className="px-5 py-4">{rule.support}%</td>
                  <td className="px-5 py-4">{rule.confidence}%</td>
                  <td className="px-5 py-4">
                    <span className="rounded-lg bg-teal-50 px-2 py-1 font-semibold text-teal-700">
                      {rule.lift}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-500">
                    订单 {rule.evidence.slice(0, 3).join("、")}
                  </td>
                  <td className="px-5 py-4">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === `rule-${rule.id}`}
                      onClick={async () => {
                        setBusy(`rule-${rule.id}`);
                        try {
                          await createRetailCampaign(rule.id);
                          toast.success("已创建运营方案");
                          await load();
                        } finally {
                          setBusy("");
                        }
                      }}
                    >
                      创建方案
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <BadgeCheck className="h-5 w-5 text-teal-600" />
            <h2 className="font-semibold">AI 运营方案</h2>
          </div>
          <div className="mt-4 space-y-3">
            {data.campaigns.map((item) => (
              <div key={item.id} className="rounded-xl border border-slate-100 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-slate-800">{item.name}</p>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                    {statusLabel[item.status] || item.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-400">版本 v{item.version} · 保留规则快照</p>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-5 w-5 text-violet-600" />
            <h2 className="font-semibold">Agent 评测与标注</h2>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            覆盖推荐准确性、活动口径、配送退款、缺货替代和越权拒答。
          </p>
          <div className="mt-4 space-y-3">
            {data.evaluations.map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between rounded-xl bg-violet-50/60 p-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-800">评测运行 #{run.id}</p>
                  <p className="mt-1 text-xs text-slate-400">配置快照已保存</p>
                </div>
                <span className="text-xs font-medium text-violet-700">
                  {statusLabel[run.status] || run.status} · 演示
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-amber-600" />
            <h2 className="font-semibold">优化任务闭环</h2>
          </div>
          <div className="mt-4 space-y-3">
            {data.tasks.map((task) => (
              <div key={task.id} className="rounded-xl border border-slate-100 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-slate-800">{task.title}</p>
                  <span className="whitespace-nowrap rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                    {statusLabel[task.status] || task.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  目标：{task.targetMetric || "完成问题验证"}
                </p>
                {nextStatus[task.status] && (
                  <Button
                    className="mt-3 w-full"
                    size="sm"
                    variant="outline"
                    disabled={busy === `task-${task.id}`}
                    onClick={async () => {
                      setBusy(`task-${task.id}`);
                      try {
                        await transitionRetailTask(task.id, nextStatus[task.status]);
                        toast.success("任务状态已推进");
                        await load();
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    推进到：{statusLabel[nextStatus[task.status]]}
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <aside className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-xs leading-6 text-amber-900">
        <strong>数据可信度说明：</strong>本地授权数据提供 9,835 个匿名购物篮和 43,367
        条商品出现记录，不含价格、时间、顾客、门店或履约；UCI CC BY 4.0 固定快照补充 5,000
        条带时间、数量、英镑单价、国家与取消标记的公开交易。两份来源分别统计，不混合声称销售增长；客服问句、处理状态和
        AI 使用事件均明确标为 synthetic。
      </aside>
    </div>
  );
}
