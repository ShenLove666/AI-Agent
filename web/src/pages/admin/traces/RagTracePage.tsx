import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Clock3, RefreshCw, Search, TrendingUp } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getRagTraceRuns, type PageResult, type RagTraceRun } from "@/services/ragTraceService";
import { getErrorMessage } from "@/utils/error";
import { RunsTable } from "@/pages/admin/traces/components/RunsTable";
import { StatCard, type StatCardTone } from "@/pages/admin/traces/components/StatCard";
import {
  PAGE_SIZE,
  normalizeStatus,
} from "@/pages/admin/traces/traceUtils";

type DurationMetric = {
  value: string;
  unit: string;
};

const formatDurationMetric = (durationMs: number): DurationMetric => {
  const duration = Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 0;
  if (duration < 1000) {
    return { value: `${Math.round(duration)}`, unit: "ms" };
  }
  if (duration < 60_000) {
    return { value: (duration / 1000).toFixed(2), unit: "s" };
  }
  return { value: (duration / 1000).toFixed(1), unit: "s" };
};

export function RagTracePage() {
  const navigate = useNavigate();
  const runsRequestRef = useRef(0);
  const [traceIdFilter, setTraceIdFilter] = useState("");
  const [queryTraceId, setQueryTraceId] = useState("");
  const [pageNo, setPageNo] = useState(1);
  const [pageData, setPageData] = useState<PageResult<RagTraceRun> | null>(null);
  const [loading, setLoading] = useState(false);

  const runs = pageData?.records || [];

  const loadRuns = async (
    current = pageNo,
    nextTraceId = queryTraceId,
    options: { silent?: boolean } = {}
  ): Promise<PageResult<RagTraceRun> | null> => {
    const { silent = false } = options;
    const requestId = ++runsRequestRef.current;
    if (!silent) setLoading(true);
    try {
      const result = await getRagTraceRuns({
        current,
        size: PAGE_SIZE,
        traceId: nextTraceId.trim() || undefined
      });
      if (runsRequestRef.current !== requestId) return null;
      setPageData(result);
      return result;
    } catch (error) {
      if (runsRequestRef.current !== requestId) return null;
      if (!silent) {
        toast.error(getErrorMessage(error, "加载链路运行列表失败"));
        console.error(error);
      }
      return null;
    } finally {
      if (runsRequestRef.current === requestId && !silent) setLoading(false);
    }
  };

  // 自适应轮询：存在 RUNNING → 800ms 刷一次；全部终态 → 5s 刷一次
  // （idle 也保持低频刷新，另一标签页的新 Trace 才会自己出现）；
  // 页面隐藏时降为 5s。递归 setTimeout（前一次返回后再排下一次）。
  const RUNNING_POLL_MS = 800;
  const IDLE_POLL_MS = 5000;

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const schedule = (delay: number) => {
      if (cancelled) return;
      timer = window.setTimeout(poll, delay);
    };

    const poll = async () => {
      if (cancelled) return;
      if (document.hidden) {
        schedule(IDLE_POLL_MS);
        return;
      }
      const result = await loadRuns(pageNo, queryTraceId, { silent: true });
      if (cancelled || !result) {
        schedule(IDLE_POLL_MS);
        return;
      }
      const hasRunning = result.records.some(
        (run) => normalizeStatus(run.status) === "running"
      );
      schedule(hasRunning ? RUNNING_POLL_MS : IDLE_POLL_MS);
    };

    // 首次/筛选变化：立即加载（非 silent，显示 loading），返回后按状态排下一轮
    void loadRuns(pageNo, queryTraceId).then((result) => {
      if (cancelled) return;
      const hasRunning = result
        ? result.records.some((run) => normalizeStatus(run.status) === "running")
        : false;
      schedule(hasRunning ? RUNNING_POLL_MS : IDLE_POLL_MS);
    });

    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageNo, queryTraceId]);

  const handleSearch = () => {
    setPageNo(1);
    setQueryTraceId(traceIdFilter.trim());
  };

  const handleRefresh = () => {
    loadRuns(pageNo, queryTraceId);
  };

  const traceStats = useMemo(() => {
    const durations = runs
      .map((item) => Number(item.durationMs ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const ttftValues = runs
      .map((item) => Number(item.ttftMs ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const successCount = runs.filter((item) => normalizeStatus(item.status) === "success").length;
    const failedCount = runs.filter((item) => normalizeStatus(item.status) === "failed").length;
    const runningCount = runs.filter((item) => normalizeStatus(item.status) === "running").length;
    // 本页总耗时（平均耗时排障价值低，改为更有意义的累计指标）
    const totalDuration = durations.reduce((sum, value) => sum + value, 0);
    const avgTtft = ttftValues.length
      ? Math.round(ttftValues.reduce((sum, value) => sum + value, 0) / ttftValues.length)
      : null; // null = 未采集，与 0ms 是两回事
    const successRate = runs.length ? Math.round((successCount / runs.length) * 1000) / 10 : 0;
    return {
      totalRuns: pageData?.total ?? runs.length,
      successCount,
      failedCount,
      runningCount,
      totalDuration,
      avgTtft,
      successRate
    };
  }, [runs, pageData?.total]);

  const current = pageData?.current || pageNo;
  const pages = pageData?.pages || 1;
  const total = pageData?.total || 0;
  const totalDurationMetric = formatDurationMetric(traceStats.totalDuration);
  // 未采集（null）→ 显示「—」，绝不显示 0ms
  const avgTtftMetric =
    traceStats.avgTtft === null ? null : formatDurationMetric(traceStats.avgTtft);
  const statCards: {
    key: string;
    title: string;
    value: string;
    unit?: string;
    icon: ReactNode;
    tone: StatCardTone;
    hint?: string;
  }[] = [
    {
      key: "status",
      title: "成功 / 失败 / 运行中",
      value: `${traceStats.successCount} / ${traceStats.failedCount} / ${traceStats.runningCount}`,
      icon: <Activity className="h-4 w-4" />,
      tone: "emerald"
    },
    {
      key: "successRate",
      title: "成功率",
      value: `${traceStats.successRate}%`,
      icon: <TrendingUp className="h-4 w-4" />,
      tone: "cyan"
    },
    {
      key: "totalDuration",
      title: "本页总耗时",
      value: totalDurationMetric.value,
      unit: totalDurationMetric.unit,
      icon: <Clock3 className="h-4 w-4" />,
      tone: "indigo"
    },
    {
      key: "avgTtft",
      title: "平均首字耗时",
      value: avgTtftMetric?.value ?? "—",
      unit: avgTtftMetric?.unit,
      icon: <Clock3 className="h-4 w-4" />,
      tone: "sky",
      // TTFT：Generation 开始 → 首个正式回答 Token
      hint: "从回答生成开始到首个正式回答 Token 的平均耗时；仅统计当前页已采集数据"
    }
  ];

  return (
    <div className="admin-page trace-page trace-list-page">
      <div className="trace-list-shell">
        <div className="admin-page-header">
          <div>
            <h1 className="admin-page-title">链路追踪</h1>
            <p className="admin-page-subtitle">
              独立列表页聚焦运行检索，点击任意运行记录进入详情页分析慢节点与失败节点
            </p>
          </div>
          <div className="admin-page-actions">
            <Input
              value={traceIdFilter}
              onChange={(event) => setTraceIdFilter(event.target.value)}
              placeholder="搜索 Trace Id"
              className="w-[300px]"
            />
            <Button className="admin-primary-gradient" onClick={handleSearch}>
              <Search className="h-4 w-4 mr-2" />
              查询
            </Button>
            <Button variant="outline" onClick={handleRefresh}>
              <RefreshCw className="h-4 w-4 mr-2" />
              刷新
            </Button>
          </div>
        </div>

        <section className="trace-list-stat-section">
          <div className="trace-list-stat-caption">
            <span className="trace-list-stat-caption-label">当前页统计</span>
            <span className="trace-list-stat-caption-hint">仅反映本页 {runs.length} 条记录</span>
          </div>
          <div className="trace-list-stat-grid">
            {statCards.map((stat) => (
              <StatCard
                key={stat.key}
                title={stat.title}
                value={stat.value}
                unit={stat.unit}
                icon={stat.icon}
                tone={stat.tone}
              />
            ))}
          </div>
        </section>

        <RunsTable
          runs={runs}
          loading={loading}
          current={current}
          pages={pages}
          total={total}
          onOpenRun={(traceId) => navigate(`/admin/traces/${encodeURIComponent(traceId)}`)}
          onPrevPage={() => setPageNo((prev) => Math.max(1, prev - 1))}
          onNextPage={() => setPageNo((prev) => prev + 1)}
        />
      </div>
    </div>
  );
}
