import { Badge } from "@/components/ui/badge";
import type { CaseProvenance } from "@/services/supportService";

const LOCAL_SOURCE_PREFIX = "user-authorized-local://";

export function CaseProvenanceView({ value }: { value: CaseProvenance | null }) {
  if (!value?.dataSource) return <p className="text-xs text-slate-500">该案例没有可用的来源关联信息。</p>;

  const sourceUri = value.dataSource.sourceUri;
  const isWebSource = /^https?:\/\//i.test(sourceUri);
  const isAuthorizedLocalSource = sourceUri.toLowerCase().startsWith(LOCAL_SOURCE_PREFIX);
  const localSourceFiles = isAuthorizedLocalSource
    ? sourceUri.slice(LOCAL_SOURCE_PREFIX.length).split("+").filter(Boolean)
    : [];

  return <section aria-label="案例数据溯源" className="rounded-lg border border-blue-200 bg-blue-50 p-4"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm">{value.dataSource.title}</strong>{value.isDemo && <Badge className="bg-amber-500 text-slate-950">DEMO 场景</Badge>}<Badge variant="outline">生成器 {value.generatorVersion || "不可用"}</Badge></div><p className="mt-2 text-xs text-slate-600">来源记录 {value.sourceRecordKey || "不可用"} · 数据版本 {value.dataSource.version}</p><p className="mt-2 text-xs text-slate-500">限制：{value.dataSource.limitations.join("；") || "未声明"}</p><div className="mt-3 flex flex-wrap gap-2">{Object.entries(value.fieldLineage).map(([field,lineage]) => <span key={field} className="rounded-full bg-white px-2 py-1 text-[11px] text-slate-600">{field}: {lineage.provenance}{lineage.method === "unavailable" ? "（不可用）" : ""}</span>)}</div>{isWebSource ? <a className="mt-3 inline-block text-xs font-medium text-blue-700 hover:underline" href={sourceUri} target="_blank" rel="noreferrer">查看来源说明 ↗</a> : isAuthorizedLocalSource ? <p className="mt-3 text-xs text-slate-600">本地授权来源：{localSourceFiles.join("、") || "未提供文件名"}。原始文件不随系统部署，无法网页预览。</p> : <p className="mt-3 text-xs text-slate-600">内部来源：该来源由系统内部管理，无法通过网页打开。</p>}</section>;
}
