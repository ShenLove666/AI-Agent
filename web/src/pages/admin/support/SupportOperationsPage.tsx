import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  BookOpenCheck,
  CheckCircle2,
  FlaskConical,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Target
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuthStore } from "@/stores/authStore";
import { KnowledgeSourcesView } from "./KnowledgeSourcesView";
import {
  activateKnowledgeRelease,
  decideKnowledgeRelease,
  getEvaluationOverview,
  getKnowledgeReleases,
  getKnowledgeSources,
  getQualityOverview,
  getSupportCoverage,
  resolveKnowledgeGap,
  runSupportEvaluation,
  type EvaluationOverview,
  type KnowledgeRelease,
  type KnowledgeSource,
  type QualityOverview,
  type SupportCoverage
} from "@/services/supportService";

export type SupportOperationsView = "knowledge" | "quality" | "evaluation" | "reports";

const titles: Record<
  SupportOperationsView,
  { title: string; description: string; icon: typeof Activity }
> = {
  knowledge: {
    title: "知识发布中心",
    description: "把知识文档冻结为可审计版本，发布后再显式启用。",
    icon: BookOpenCheck
  },
  quality: {
    title: "回复质量与知识缺口",
    description: "从人工审核失败中定位高频问题，并绑定知识版本完成修复。",
    icon: ShieldAlert
  },
  evaluation: {
    title: "上线前评测",
    description: "使用固定评测集比较候选版本，高风险失败会阻断上线。",
    icon: FlaskConical
  },
  reports: {
    title: "客服运营报告",
    description: "指标来自工单事件与人工决策；演示数据会明确标注。",
    icon: Activity
  }
};

const fmt = (value: number | null | undefined, suffix = "") =>
  value == null ? "暂无数据" : `${value}${suffix}`;

export function SupportOperationsPage({ view = "reports" }: { view?: SupportOperationsView }) {
  const permissions = useAuthStore((state) => state.user?.permissions ?? []);
  const [releases, setReleases] = useState<KnowledgeRelease[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [quality, setQuality] = useState<QualityOverview | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationOverview | null>(null);
  const [coverage, setCoverage] = useState<SupportCoverage | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const meta = titles[view];
  const Icon = meta.icon;
  const active = useMemo(() => releases.find((item) => item.isActive) ?? null, [releases]);
  const candidate = useMemo(
    () => releases.find((item) => item.status === "published" && !item.isActive) ?? active,
    [releases, active]
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 按视图只请求本视图需要的数据：避免无权限的请求触发 403 报错
      // （如主管在质量视图不再请求 knowledge.manage 接口）
      const requests: Array<Promise<unknown>> = [];
      if (view === "knowledge") {
        requests.push(
          getKnowledgeReleases().then(setReleases),
          getKnowledgeSources().then(setSources)
        );
      } else if (view === "quality") {
        requests.push(
          getQualityOverview().then(setQuality),
          getSupportCoverage().then(setCoverage)
        );
        // 解决缺口需绑定知识版本（knowledge.manage）：只有该权限的用户才加载版本列表
        if (permissions.includes("knowledge.manage")) {
          requests.push(getKnowledgeReleases().then(setReleases));
        }
      } else if (view === "evaluation") {
        requests.push(getEvaluationOverview().then(setEvaluation));
        // 上线决策需绑定候选版本（该视图仅 admin 可进入）
        requests.push(getKnowledgeReleases().then(setReleases));
      } else {
        // reports：聚合全部只读数据（单项失败不阻断整体展示）
        const safe = <T,>(promise: Promise<T>) => promise.catch(() => null);
        requests.push(
          safe(getQualityOverview()).then((value) => setQuality(value)),
          safe(getEvaluationOverview()).then((value) => setEvaluation(value)),
          safe(getSupportCoverage()).then((value) => setCoverage(value))
        );
      }
      await Promise.all(requests);
    } catch {
      toast.error("运营闭环数据加载失败，请确认后端已启动并完成迁移");
    } finally {
      setLoading(false);
    }
  }, [view]);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (task: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await task();
      toast.success(message);
      await load();
    } catch {
      toast.error("操作未完成，请检查版本状态或高风险门禁");
    } finally {
      setBusy(false);
    }
  };
  if (loading)
    return (
      <div role="status" className="p-10 text-sm text-slate-500">
        正在加载客服运营数据…
      </div>
    );

  return (
    <div className="mx-auto max-w-[1480px] space-y-5 pb-10">
      <section className="rounded-[28px] border border-indigo-100 bg-gradient-to-r from-white via-indigo-50/70 to-blue-50 p-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div>
            <Badge className="mb-3 bg-indigo-600">
              <Sparkles className="mr-1 h-3.5 w-3.5" />
              AI 客服质量闭环
            </Badge>
            <h1 className="flex items-center gap-3 text-3xl font-semibold text-slate-950">
              <Icon className="h-8 w-8 text-indigo-600" />
              {meta.title}
            </h1>
            <p className="mt-2 text-sm text-slate-600">{meta.description}</p>
          </div>
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            刷新
          </Button>
        </div>
      </section>

      {view === "knowledge" && (
        <section className="grid gap-4 lg:grid-cols-[1.4fr_.6fr]">
          <div className="rounded-2xl border bg-white p-5">
            <h2 className="font-semibold">版本历史</h2>
            <div className="mt-4 space-y-3">
              {releases.length === 0 ? (
                <p className="text-sm text-slate-500">暂无版本，请先在知识库上传并解析文档。</p>
              ) : (
                releases.map((item) => (
                  <article key={item.id} className="rounded-xl border border-slate-200 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <strong>{item.version}</strong>
                          {item.isActive && <Badge className="bg-emerald-600">当前生效</Badge>}
                          <Badge variant="outline">{item.status}</Badge>
                        </div>
                        <p className="mt-1 text-sm text-slate-600">
                          {item.title} · {item.documents.length} 份冻结文档
                        </p>
                      </div>
                      {item.status === "published" && !item.isActive && (
                        <Button
                          disabled={busy}
                          onClick={() =>
                            void act(
                              () => activateKnowledgeRelease(item.id),
                              `已切换到 ${item.version}`
                            )
                          }
                        >
                          启用此版本
                        </Button>
                      )}
                    </div>
                    <p className="mt-3 break-all text-xs text-slate-400">
                      内容快照 {item.contentHash.slice(0, 16)}… · {item.retrievalMode}
                    </p>
                  </article>
                ))
              )}
            </div>
          </div>
          <aside className="rounded-2xl border bg-slate-950 p-5 text-white">
            <BookOpenCheck className="h-7 w-7 text-indigo-300" />
            <h2 className="mt-4 text-lg font-semibold">发布规则</h2>
            <ul className="mt-3 space-y-3 text-sm text-slate-300">
              <li>1. 文档必须完成解析且可检索</li>
              <li>2. 发布后成员关系与哈希不可变</li>
              <li>3. 切换版本不会删除历史版本</li>
              <li>4. 正式回复只检索当前生效版本</li>
            </ul>
          </aside>
        </section>
      )}

      {view === "knowledge" && (
        <KnowledgeSourcesView sources={sources} />
      )}

      {view === "quality" && (
        <section className="grid gap-4 lg:grid-cols-[.65fr_1.35fr]">
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            <Metric label="已复核" value={quality?.reviewed} />
            <Metric label="质检通过" value={quality?.passed} />
            <Metric label="待修缺口" value={quality?.openGaps} />
          </div>
          <div className="rounded-2xl border bg-white p-5">
            <h2 className="font-semibold">知识缺口队列</h2>
            <div className="mt-4 space-y-3">
              {quality?.gaps.length ? (
                quality.gaps.map((gap) => (
                  <article
                    key={gap.id}
                    className="flex flex-col justify-between gap-3 rounded-xl border p-4 md:flex-row md:items-center"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <strong>{gap.title}</strong>
                        <Badge variant="outline">{gap.severity}</Badge>
                        <Badge variant="outline">{gap.status}</Badge>
                      </div>
                      <p className="mt-1 text-sm text-slate-500">
                        {gap.category} · 出现 {gap.occurrenceCount} 次 · 证据 {gap.evidence.length}{" "}
                        条
                      </p>
                    </div>
                    {gap.status === "open" && active && (
                      <Button
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => resolveKnowledgeGap(gap.id, active.id),
                            `缺口已绑定 ${active.version}`
                          )
                        }
                      >
                        用当前版本解决
                      </Button>
                    )}
                  </article>
                ))
              ) : (
                <p className="text-sm text-slate-500">当前没有待处理知识缺口。</p>
              )}
            </div>
          </div>
        </section>
      )}

      {view === "evaluation" && (
        <section className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label="固定评测集" value={evaluation?.datasetCount} />
            <Metric label="评测用例" value={evaluation?.evaluationCaseCount} />
            <Metric label="候选知识版本" value={candidate?.version ?? "无"} />
          </div>
          <div className="rounded-2xl border bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">评测运行与上线门禁</h2>
                <p className="mt-1 text-sm text-slate-500">
                  规则评分可复现；引用或拒答失败会标记为高风险。
                </p>
              </div>
              {candidate && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    void act(() => runSupportEvaluation(candidate.id), "候选版本评测完成")
                  }
                >
                  <Target className="mr-2 h-4 w-4" />
                  运行评测
                </Button>
              )}
            </div>
            <div className="mt-4 space-y-3">
              {evaluation?.runs.length ? (
                evaluation.runs.map((run) => (
                  <article
                    key={run.id}
                    className="flex flex-col justify-between gap-3 rounded-xl border p-4 md:flex-row md:items-center"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <strong>运行 #{run.id}</strong>
                        <Badge className={run.gate === "passed" ? "bg-emerald-600" : "bg-rose-600"}>
                          {run.gate === "passed" ? "门禁通过" : "阻断上线"}
                        </Badge>
                      </div>
                      <p className="mt-1 text-sm text-slate-500">
                        {run.caseCount} 用例 · 得分 {fmt(run.score)} · 高风险失败{" "}
                        {run.highRiskFailures}
                      </p>
                    </div>
                    {candidate && run.gate === "passed" && (
                      <Button
                        disabled={busy}
                        onClick={() =>
                          void act(
                            () => decideKnowledgeRelease(run.id, candidate.id, "approved"),
                            `${candidate.version} 已批准上线`
                          )
                        }
                      >
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                        批准上线
                      </Button>
                    )}
                  </article>
                ))
              ) : (
                <p className="text-sm text-slate-500">尚无评测运行。选择候选版本开始第一次评测。</p>
              )}
            </div>
          </div>
        </section>
      )}

      {view === "reports" && (
        <Reports quality={quality} evaluation={evaluation} releases={releases} coverage={coverage} />
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string | undefined }) {
  return (
    <div className="rounded-2xl border bg-white p-5">
      <p className="text-sm text-slate-500">{label}</p>
      <strong className="mt-2 block text-3xl text-slate-950">{value ?? "—"}</strong>
    </div>
  );
}

function Reports({
  quality,
  evaluation,
  releases,
  coverage
}: {
  quality: QualityOverview | null;
  evaluation: EvaluationOverview | null;
  releases: KnowledgeRelease[];
  coverage: SupportCoverage | null;
}) {
  const latest = evaluation?.runs[0];
  return (
    <>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="人工复核量" value={quality?.reviewed} />
        <Metric
          label="质检通过率"
          value={
            quality?.reviewed
              ? `${Math.round((quality.passed / quality.reviewed) * 100)}%`
              : "暂无数据"
          }
        />
        <Metric label="待修知识缺口" value={quality?.openGaps} />
        <Metric label="最近评测得分" value={fmt(latest?.score)} />
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border bg-white p-5">
          <h2 className="font-semibold">知识健康度</h2>
          <div className="mt-5 flex items-end gap-3">
            <strong className="text-4xl">
              {releases.filter((item) => item.status === "published").length}
            </strong>
            <span className="pb-1 text-sm text-slate-500">个已发布版本</span>
          </div>
          <p className="mt-4 text-sm text-slate-600">
            当前生效：{releases.find((item) => item.isActive)?.version ?? "未设置"}
          </p>
        </div>
        <div className="rounded-2xl border bg-slate-950 p-5 text-white">
          <h2 className="font-semibold">数据口径</h2>
          <p className="mt-4 text-sm leading-6 text-slate-300">
            本页不调用大模型编造指标。复核量来自人工决策记录，知识缺口来自质检聚合，评测得分来自固定用例与确定性规则。
          </p>
          <Badge className="mt-4 bg-amber-500 text-slate-950">
            {quality?.provenance === "demo" ? "当前为演示数据" : "当前含真实业务数据"}
          </Badge>
        </div>
      </section>
      <section className="rounded-xl border bg-white p-5" aria-label="案例覆盖与数据口径">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">案例覆盖与数据口径</h2><p className="mt-1 text-xs text-slate-500">真实观测字段与生成场景分开统计，不把演示结果包装成线上效果。</p></div><Badge className={coverage?.provenance === "production" ? "bg-emerald-600" : "bg-amber-500 text-slate-950"}>{coverage?.provenance === "mixed" ? "混合数据" : coverage?.provenance === "production" ? "正式数据" : "演示数据"}</Badge></div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3"><Metric label="来源关联演示案例" value={coverage?.demoCases ?? 0}/><Metric label="普通业务案例" value={coverage?.ordinaryCases ?? 0}/><Metric label="案例总量" value={coverage?.totalCases ?? 0}/></div>
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-600">{Object.entries(coverage?.sourceVersions ?? {}).map(([version,count]) => <span key={version} className="rounded-md border bg-slate-50 px-2 py-1">来源版本 {version} · {count} 条</span>)}</div>
        {!!coverage?.unsupportedSegments.length && <p className="mt-3 text-xs text-amber-700">暂未覆盖：{coverage.unsupportedSegments.join("、")}</p>}
      </section>
    </>
  );
}
