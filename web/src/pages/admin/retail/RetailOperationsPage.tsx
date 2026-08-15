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
  FileText,
  RefreshCw,
  Send,
  ShoppingBasket,
  Sparkles,
  Store,
  Target,
  TriangleAlert,
  UserRound,
  XCircle
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/authStore";
import { DataSourcesView } from "./DataSourcesView";
import {
  assignRetailTask,
  createRetailCampaign,
  getRetailCampaign,
  getRetailOverview,
  getRetailReport,
  getRetailTask,
  syncFailedEvaluations,
  transitionRetailCampaign,
  transitionRetailTask,
  verifyRetailTask,
  type RetailCampaign,
  type RetailCampaignDetail,
  type RetailOverview,
  type RetailTask,
  type RetailTaskDetail
} from "@/services/retailService";

const statusLabel: Record<string, string> = {
  draft: "待确认",
  confirmed: "已确认",
  published: "已发布",
  rejected: "已驳回",
  new: "待确认",
  optimizing: "优化中",
  pending_verification: "待复测",
  resolved: "已解决",
  completed: "已完成",
  pending: "待执行",
  running: "计算中",
  insufficient_data: "数据不足",
  failed: "失败"
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
  const permissions = useAuthStore((state) => state.user?.permissions ?? []);
  const canCreate = permissions.includes("campaign.create");
  const canConfirm = permissions.includes("campaign.confirm");
  const canPublish = permissions.includes("campaign.publish");
  const canUpdateTask = permissions.includes("task.update");

  const [data, setData] = useState<RetailOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  // 方案详情抽屉
  const [campaignDetail, setCampaignDetail] = useState<RetailCampaignDetail | null>(null);
  const [campaignDetailOpen, setCampaignDetailOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  // 任务详情抽屉
  const [taskDetail, setTaskDetail] = useState<RetailTaskDetail | null>(null);
  const [taskDetailOpen, setTaskDetailOpen] = useState(false);
  const [assigneeId, setAssigneeId] = useState("");
  const [changeVersion, setChangeVersion] = useState("");

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

  const openCampaignDetail = async (campaign: RetailCampaign) => {
    setBusy(`campaign-open-${campaign.id}`);
    try {
      const detail = await getRetailCampaign(campaign.id);
      setCampaignDetail(detail);
      setRejectReason("");
      setCampaignDetailOpen(true);
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const openTaskDetail = async (task: RetailTask) => {
    setBusy(`task-open-${task.id}`);
    try {
      const detail = await getRetailTask(task.id);
      setTaskDetail(detail);
      setAssigneeId(detail.assigneeId ? String(detail.assigneeId) : "");
      setChangeVersion(detail.changeVersion ?? "");
      setTaskDetailOpen(true);
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const transitionCampaign = async (
    action: "confirm" | "reject" | "publish",
    detail: RetailCampaignDetail
  ) => {
    if (action === "reject" && !rejectReason.trim()) {
      toast.error("请填写驳回原因");
      return;
    }
    setBusy(`campaign-${action}`);
    try {
      await transitionRetailCampaign(
        detail.id,
        action,
        detail.lockVersion,
        action === "reject" ? rejectReason : undefined
      );
      toast.success(
        action === "confirm"
          ? "方案已确认，已自动创建优化任务（复测走经营效果验证，与 AI 评测分离）"
          : action === "publish"
            ? "方案已发布"
            : "方案已驳回"
      );
      setCampaignDetailOpen(false);
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const createCampaign = async (ruleId: number) => {
    setBusy(`rule-${ruleId}`);
    try {
      await createRetailCampaign(ruleId);
      toast.success("已创建运营方案");
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const advanceTask = async (task: RetailTaskDetail) => {
    const target = nextStatus[task.status];
    if (!target) return;
    if (target === "pending_verification" && !changeVersion.trim()) {
      toast.error("进入待复测必须填写关联的配置或知识版本号");
      return;
    }
    setBusy(`task-${task.id}`);
    try {
      await transitionRetailTask(
        task.id,
        target,
        target === "pending_verification" ? changeVersion : undefined
      );
      toast.success(`任务已推进到：${statusLabel[target]}`);
      setTaskDetailOpen(false);
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const assignTask = async (task: RetailTaskDetail) => {
    setBusy(`task-assign-${task.id}`);
    try {
      await assignRetailTask(task.id, assigneeId ? Number(assigneeId) : null);
      toast.success(assigneeId ? "任务已分派" : "已取消分派");
      setTaskDetailOpen(false);
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const startVerify = async (task: RetailTaskDetail) => {
    setBusy(`task-verify-${task.id}`);
    try {
      const result = await verifyRetailTask(task.id);
      if (task.sourceType === "campaign") {
        toast.success(`经营效果复测 #${result.runId} 已执行并写入修改后指标`);
      } else {
        toast.success(`AI 评测复测 #${result.runId} 已创建，后台执行中（失败清零后才可标记已解决）`);
      }
      setTaskDetailOpen(false);
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  const syncFromEvaluations = async () => {
    setBusy("sync-evaluations");
    try {
      const result = await syncFailedEvaluations();
      toast.success(result.created > 0 ? `已补建 ${result.created} 个优化任务` : "没有需要补建的任务");
      await load();
    } catch {
      /* interceptor shows message */
    } finally {
      setBusy("");
    }
  };

  if (loading && !data)
    return (
      <div className="space-y-4">
        <div className="h-48 animate-pulse rounded-lg bg-slate-100" />
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      </div>
    );

  if (error && !data)
    return (
      <div
        role="alert"
        className="rounded-lg border border-rose-200 bg-rose-50 p-8 text-center"
      >
        <TriangleAlert className="mx-auto h-10 w-10 text-rose-500" />
        <h1 className="mt-4 text-xl font-semibold text-rose-900">即时零售数据加载失败</h1>
        <p className="mt-2 text-sm text-rose-700">{error}</p>
        <Button className="mt-5" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />
          重试
        </Button>
      </div>
    );

  if (!data || data.dataState === "empty")
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center">
        <ShoppingBasket className="mx-auto h-10 w-10 text-slate-300" />
        <h1 className="mt-4 text-xl font-semibold">还没有即时零售数据</h1>
        <p className="mt-2 text-sm text-slate-500">
          运行 seed-retail 命令导入购物篮后即可查看真实关联洞察。
        </p>
      </div>
    );

  return (
    <div className="space-y-6 pb-10">
      <section className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="rounded-md border border-indigo-100 bg-indigo-50 p-1 text-indigo-600">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Instant Retail AI Operations
            </span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {data.profile?.name}
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
            从真实购物篮发现搭配机会，把运营方案发布到 AI 客服，再用评测、标注和优化任务验证效果。
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs text-slate-600">
              {data.profile?.businessType}
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs text-slate-600">
              {data.profile?.storeCount
                ? `${data.profile.storeCount} 家门店`
                : "源数据未提供门店维度"}
            </span>
            <OriginBadge origin="observed" />
            <OriginBadge origin="synthetic" />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />
            刷新
          </Button>
          <Button onClick={() => void downloadReport()}>
            <Download className="mr-2 h-4 w-4" />
            生成运营周报
          </Button>
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
            className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm"
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
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
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
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
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

      <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
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
                    {canCreate && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy === `rule-${rule.id}`}
                        onClick={() => void createCampaign(rule.id)}
                      >
                        创建方案
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <BadgeCheck className="h-5 w-5 text-teal-600" />
            <h2 className="font-semibold">AI 运营方案</h2>
          </div>
          <div className="mt-4 space-y-3">
            {data.campaigns.length === 0 && (
              <div className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-xs text-slate-400">
                暂无方案，可在上方关联规则表中创建
              </div>
            )}
            {data.campaigns.map((item) => (
              <button
                key={item.id}
                type="button"
                className="w-full rounded-xl border border-slate-100 p-3 text-left transition hover:border-teal-200 hover:bg-teal-50/30"
                disabled={busy === `campaign-open-${item.id}`}
                onClick={() => void openCampaignDetail(item)}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-slate-800">{item.name}</p>
                  <span className="whitespace-nowrap rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                    {statusLabel[item.status] || item.status}
                  </span>
                </div>
                {item.rule ? (
                  <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs">
                    <p className="font-medium text-slate-700">
                      {item.rule.from}
                      <ArrowRight className="mx-1 inline h-3 w-3 text-teal-600" />
                      {item.rule.to}
                    </p>
                    <p className="mt-1 text-slate-500">
                      共现 {item.rule.count} 单 · 支持度 {item.rule.support}% · 置信度{" "}
                      {item.rule.confidence}% · 提升度 {item.rule.lift}
                    </p>
                  </div>
                ) : null}
                <p className="mt-2 text-xs text-slate-400">
                  版本 v{item.version} · 保留规则快照 · 点击查看详情
                </p>
              </button>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
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
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-amber-600" />
            <h2 className="font-semibold">优化任务闭环</h2>
          </div>
          <div className="mt-4 space-y-3">
            {data.tasks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center">
                <p className="text-xs leading-5 text-slate-400">
                  暂无优化任务。任务会在方案确认、评测失败或客服知识缺口时自动创建。
                </p>
                {canUpdateTask && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-3"
                    disabled={busy === "sync-evaluations"}
                    onClick={() => void syncFromEvaluations()}
                  >
                    从失败评测创建任务
                  </Button>
                )}
              </div>
            ) : (
              data.tasks.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  className="w-full rounded-xl border border-slate-100 p-3 text-left transition hover:border-amber-200 hover:bg-amber-50/30"
                  disabled={busy === `task-open-${task.id}`}
                  onClick={() => void openTaskDetail(task)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-slate-800">{task.title}</p>
                    <span className="whitespace-nowrap rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                      {statusLabel[task.status] || task.status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">
                    目标：{task.targetMetric || "完成问题验证"}
                    {task.sourceType ? ` · 来源：${sourceTypeLabel(task.sourceType)}` : ""}
                    {task.businessVerificationRunId ? (
                      <>
                        {" · "}
                        复测 #{task.businessVerificationRunId}
                        {task.businessVerificationStatus
                          ? `（${statusLabel[task.businessVerificationStatus] || task.businessVerificationStatus}）`
                          : ""}
                      </>
                    ) : (
                      ""
                    )}
                    {nextStatus[task.status] ? " · 点击查看详情并推进" : " · 点击查看详情"}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>
      </section>

      {/* 方案详情抽屉 */}
      <Dialog open={campaignDetailOpen} onOpenChange={setCampaignDetailOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          {campaignDetail && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {campaignDetail.name}
                  <Badge
                    variant={
                      campaignDetail.status === "published"
                        ? "default"
                        : campaignDetail.status === "rejected"
                          ? "destructive"
                          : "outline"
                    }
                  >
                    {statusLabel[campaignDetail.status] || campaignDetail.status}
                  </Badge>
                </DialogTitle>
                <DialogDescription>
                  版本 v{campaignDetail.version} · 创建于{" "}
                  {campaignDetail.createdAt.slice(0, 10)}
                  {campaignDetail.publishedAt
                    ? ` · 发布于 ${campaignDetail.publishedAt.slice(0, 10)}`
                    : ""}
                </DialogDescription>
              </DialogHeader>

              {campaignDetail.rule && (
                <div className="rounded-xl bg-slate-50 p-4">
                  <p className="text-sm font-medium text-slate-700">关联规则（证据快照）</p>
                  <p className="mt-2 text-sm text-slate-800">
                    共现 {campaignDetail.rule.count} 单 · 支持度 {campaignDetail.rule.support}% ·
                    置信度 {campaignDetail.rule.confidence}% · 提升度 {campaignDetail.rule.lift}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    证据订单：{campaignDetail.rule.evidence.slice(0, 8).join("、") || "无"}
                  </p>
                </div>
              )}

              <div className="space-y-3">
                {campaignDetail.versions.map((version) => (
                  <div key={version.version} className="rounded-xl border border-slate-100 p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-600">
                        方案文案 · v{version.version} · {version.channel}
                      </span>
                      {version.approvedAt && (
                        <span className="text-xs text-teal-600">
                          已确认于 {version.approvedAt.slice(0, 10)}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-700">{version.copy}</p>
                  </div>
                ))}
              </div>

              {campaignDetail.rejectedReason && (
                <div className="rounded-xl border border-rose-100 bg-rose-50 p-4 text-sm text-rose-700">
                  驳回原因：{campaignDetail.rejectedReason}
                </div>
              )}

              {campaignDetail.task && (
                <div className="rounded-xl bg-amber-50/60 p-3 text-xs text-slate-600">
                  关联优化任务：{campaignDetail.task.title}（{statusLabel[campaignDetail.task.status]}）
                </div>
              )}

              {campaignDetail.status === "draft" && canConfirm && (
                <div className="rounded-xl border border-slate-100 p-4">
                  <Label htmlFor="reject-reason">驳回原因（驳回时必填）</Label>
                  <Input
                    id="reject-reason"
                    className="mt-2"
                    placeholder="例如：毛利不满足投放要求"
                    value={rejectReason}
                    onChange={(event) => setRejectReason(event.target.value)}
                  />
                </div>
              )}

              <DialogFooter className="gap-2">
                {campaignDetail.status === "draft" && canConfirm && (
                  <>
                    <Button
                      variant="destructive"
                      disabled={busy === "campaign-reject"}
                      onClick={() => void transitionCampaign("reject", campaignDetail)}
                    >
                      <XCircle className="mr-2 h-4 w-4" />
                      驳回方案
                    </Button>
                    <Button
                      disabled={busy === "campaign-confirm"}
                      onClick={() => void transitionCampaign("confirm", campaignDetail)}
                    >
                      <Check className="mr-2 h-4 w-4" />
                      确认方案
                    </Button>
                  </>
                )}
                {campaignDetail.status === "confirmed" && canPublish && (
                  <Button
                    disabled={busy === "campaign-publish"}
                    onClick={() => void transitionCampaign("publish", campaignDetail)}
                  >
                    <Send className="mr-2 h-4 w-4" />
                    发布方案
                  </Button>
                )}
                {(campaignDetail.status === "published" ||
                  campaignDetail.status === "rejected") && (
                  <span className="text-xs text-slate-400">
                    该状态为终态，如需调整请重新创建方案
                  </span>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* 任务详情抽屉 */}
      <Dialog open={taskDetailOpen} onOpenChange={setTaskDetailOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          {taskDetail && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {taskDetail.title}
                  <Badge variant="outline">
                    {statusLabel[taskDetail.status] || taskDetail.status}
                  </Badge>
                </DialogTitle>
                <DialogDescription>
                  来源：{sourceTypeLabel(taskDetail.sourceType)} #{taskDetail.sourceId}
                  {taskDetail.businessVerificationRun
                    ? ` · 经营效果复测 #${taskDetail.businessVerificationRun.id}`
                    : ""}
                </DialogDescription>
              </DialogHeader>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">目标指标</p>
                  <p className="mt-1 font-medium text-slate-800">
                    {taskDetail.targetMetric || "-"}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">关联版本号</p>
                  <p className="mt-1 font-medium text-slate-800">
                    {taskDetail.changeVersion || "未关联"}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">负责人</p>
                  <p className="mt-1 font-medium text-slate-800">
                    {taskDetail.assigneeId ? `用户 #${taskDetail.assigneeId}` : "未分派"}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">复测状态</p>
                  <p className="mt-1 font-medium text-slate-800">
                    {taskDetail.businessVerificationRun
                      ? statusLabel[taskDetail.businessVerificationRun.status] || taskDetail.businessVerificationRun.status
                      : "未发起"}
                  </p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">指标（前后 / 样本量）</p>
                  <p className="mt-1 font-medium text-slate-800">
                    {taskDetail.businessVerificationRun?.beforeValue != null
                      ? `${taskDetail.businessVerificationRun.beforeValue}% → ${taskDetail.businessVerificationRun.afterValue ?? "—"}%（${taskDetail.businessVerificationRun.baselineSampleSize} / ${taskDetail.businessVerificationRun.experimentSampleSize} 篮）`
                      : "无数据"}
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-slate-100 p-3">
                  <p className="text-xs font-semibold text-slate-600">修改前证据</p>
                  <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[11px] text-slate-500">
                    {JSON.stringify(taskDetail.beforeEvidence, null, 2)}
                  </pre>
                </div>
                <div className="rounded-xl border border-slate-100 p-3">
                  <p className="text-xs font-semibold text-slate-600">修改后证据（复测）</p>
                  {Object.keys(taskDetail.afterEvidence).length === 0 ? (
                    <p className="mt-2 text-xs text-slate-400">
                      复测完成后写入修改后指标，未完成前不可标记已解决
                    </p>
                  ) : (
                    <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-[11px] text-slate-500">
                      {JSON.stringify(taskDetail.afterEvidence, null, 2)}
                    </pre>
                  )}
                </div>
              </div>

              {taskDetail.status === "optimizing" && canUpdateTask && (
                <div className="rounded-xl border border-slate-100 p-4">
                  <Label htmlFor="task-assignee">
                    分派给用户（输入用户 ID，留空取消分派）
                  </Label>
                  <Input
                    id="task-assignee"
                    className="mt-2"
                    type="number"
                    placeholder="用户 ID"
                    value={assigneeId}
                    onChange={(event) => setAssigneeId(event.target.value)}
                  />
                </div>
              )}
              {(taskDetail.status === "optimizing" || taskDetail.status === "pending_verification") &&
                nextStatus[taskDetail.status] === "pending_verification" && (
                  <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-4">
                    <Label htmlFor="task-version">关联配置/知识版本号（进入待复测必填）</Label>
                    <Input
                      id="task-version"
                      className="mt-2"
                      placeholder="例如 v3 或 knowledge-release-12"
                      value={changeVersion}
                      onChange={(event) => setChangeVersion(event.target.value)}
                    />
                  </div>
                )}
              {taskDetail.status === "pending_verification" && (
                <p className="text-xs leading-5 text-slate-500">
                  已进入待复测。请先「发起复测」，复测运行完成后将修改后指标写入任务，才能标记已解决。
                </p>
              )}

              <DialogFooter className="gap-2">
                {taskDetail.status === "optimizing" && canUpdateTask && (
                  <Button
                    variant="outline"
                    disabled={busy === `task-assign-${taskDetail.id}`}
                    onClick={() => void assignTask(taskDetail)}
                  >
                    <UserRound className="mr-2 h-4 w-4" />
                    保存分派
                  </Button>
                )}
                {(taskDetail.status === "optimizing" ||
                  taskDetail.status === "pending_verification") &&
                  canUpdateTask && (
                    <Button
                      variant="outline"
                      disabled={busy === `task-verify-${taskDetail.id}`}
                      onClick={() => void startVerify(taskDetail)}
                    >
                      <FileText className="mr-2 h-4 w-4" />
                      发起复测
                    </Button>
                  )}
                {nextStatus[taskDetail.status] && canUpdateTask && (
                  <Button
                    disabled={busy === `task-${taskDetail.id}`}
                    onClick={() => void advanceTask(taskDetail)}
                  >
                    推进到：{statusLabel[nextStatus[taskDetail.status]]}
                  </Button>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <aside className="rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-xs leading-6 text-amber-900">
        <strong>数据可信度说明：</strong>本地授权数据提供 9,835 个匿名购物篮和 43,367
        条商品出现记录，不含价格、时间、顾客、门店或履约；UCI CC BY 4.0 固定快照补充 5,000
        条带时间、数量、英镑单价、国家与取消标记的公开交易。两份来源分别统计，不混合声称销售增长；客服问句、处理状态和
        AI 使用事件均明确标为 synthetic。
      </aside>
    </div>
  );
}

function sourceTypeLabel(sourceType: string): string {
  const labels: Record<string, string> = {
    campaign: "运营方案",
    evaluation: "评测运行",
    knowledge_gap: "客服知识缺口",
    basket_rule: "购物篮规则"
  };
  return labels[sourceType] ?? sourceType;
}
