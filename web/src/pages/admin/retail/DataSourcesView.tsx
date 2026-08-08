import { useEffect, useState } from "react";
import { Database, ExternalLink, Loader2, TriangleAlert, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getRetailDataSourceQuality,
  getRetailDataSources,
  type RetailDataSource,
  type RetailDataSourceQuality
} from "@/services/retailService";

export function DataSourcesView() {
  const [sources, setSources] = useState<RetailDataSource[]>([]);
  const [quality, setQuality] = useState<RetailDataSourceQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    getRetailDataSources()
      .then(setSources)
      .catch(() => setError("数据来源加载失败"))
      .finally(() => setLoading(false));
  }, []);
  const inspect = async (source: RetailDataSource) => {
    setError("");
    try {
      setQuality(await getRetailDataSourceQuality(source.id));
    } catch {
      setError("数据质量详情加载失败");
    }
  };
  if (loading)
    return (
      <div role="status" className="p-6 text-sm text-slate-500">
        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
        正在加载数据来源…
      </div>
    );
  if (error && sources.length === 0)
    return (
      <div role="alert" className="p-6 text-sm text-rose-700">
        <TriangleAlert className="mr-2 inline h-4 w-4" />
        {error}
      </div>
    );
  if (!sources.length)
    return (
      <div className="p-8 text-center text-sm text-slate-500">
        暂无已验证数据来源，请先运行零售数据导入。
      </div>
    );
  return (
    <section aria-labelledby="data-sources-title" className="rounded-xl border bg-white">
      <div className="flex items-center justify-between border-b px-5 py-4">
        <div>
          <h2 id="data-sources-title" className="font-semibold">
            数据来源
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            只展示可追溯快照；演示场景不等于真实经营效果。
          </p>
        </div>
        <Badge variant="outline">{sources.length} 个来源</Badge>
      </div>
      {error && (
        <p role="alert" className="mx-5 mt-4 text-sm text-rose-700">
          {error}
        </p>
      )}
      <div className="divide-y">
        {sources.map((source) => (
          <article
            key={source.id}
            className="grid gap-3 p-5 lg:grid-cols-[1fr_auto] lg:items-center"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Database className="h-4 w-4 text-teal-600" />
                <strong>{source.title}</strong>
                {source.isDemo && <Badge className="bg-amber-500 text-slate-950">DEMO 数据</Badge>}
                <Badge variant="outline">{source.version}</Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {source.publisher} · {source.license} · 获取于 {source.retrievedAt.slice(0, 10)}
              </p>
              <p className="mt-2 text-xs text-slate-600">
                限制：{source.limitations.join("；") || "未声明"}
              </p>
              <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
                <span>转换 {source.transformVersion}</span>
                <span>接受 {source.acceptedRows}</span>
                <span>拒绝 {source.rejectedRows}</span>
                <span>SHA {source.manifestSha256.slice(0, 12)}</span>
              </div>
            </div>
            <div className="flex gap-2">
              <a
                href={source.sourceUri}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center rounded-md border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                原始来源
                <ExternalLink className="ml-1 h-3 w-3" />
              </a>
              <Button size="sm" variant="outline" onClick={() => void inspect(source)}>
                查看质量
              </Button>
            </div>
          </article>
        ))}
      </div>
      {quality && (
        <aside role="dialog" aria-label="数据质量详情" className="border-t bg-slate-50 p-5">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold">质量与选择口径 · {quality.datasetKey}</h3>
              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                <span>
                  来源版本 {quality.version} · 转换 {quality.transformVersion}
                </span>
                <Badge className="bg-emerald-600">observed</Badge>
              </div>
            </div>
            <Button
              aria-label="关闭质量详情"
              size="icon"
              variant="ghost"
              onClick={() => setQuality(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-xs font-semibold">选择规则</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">
                {quality.selectionRules.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-xs font-semibold">不可用与限制</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">
                {quality.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </aside>
      )}
    </section>
  );
}
