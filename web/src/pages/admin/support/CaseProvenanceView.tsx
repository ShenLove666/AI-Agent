import { Badge } from "@/components/ui/badge";
import type { CaseProvenance } from "@/services/supportService";

export function CaseProvenanceView({ value }: { value: CaseProvenance | null }) {
  if (!value?.dataSource) return <p className="text-xs text-slate-500">该案例没有可用的来源关联信息。</p>;
  return <section aria-label="案例数据溯源" className="rounded-lg border border-blue-200 bg-blue-50 p-4"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm">{value.dataSource.title}</strong>{value.isDemo && <Badge className="bg-amber-500 text-slate-950">DEMO 场景</Badge>}<Badge variant="outline">生成器 {value.generatorVersion || "不可用"}</Badge></div><p className="mt-2 text-xs text-slate-600">来源记录 {value.sourceRecordKey || "不可用"} · 数据版本 {value.dataSource.version}</p><p className="mt-2 text-xs text-slate-500">限制：{value.dataSource.limitations.join("；") || "未声明"}</p><div className="mt-3 flex flex-wrap gap-2">{Object.entries(value.fieldLineage).map(([field,lineage]) => <span key={field} className="rounded-full bg-white px-2 py-1 text-[11px] text-slate-600">{field}: {lineage.provenance}{lineage.method === "unavailable" ? "（不可用）" : ""}</span>)}</div><a className="mt-3 inline-block text-xs font-medium text-blue-700 hover:underline" href={value.dataSource.sourceUri} target="_blank" rel="noreferrer">查看来源说明 ↗</a></section>;
}
