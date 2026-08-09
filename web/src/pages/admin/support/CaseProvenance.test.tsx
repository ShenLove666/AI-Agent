import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CaseProvenanceView } from "./CaseProvenanceView";

describe("CaseProvenance", () => it("shows source version, generator and unavailable fields", () => {
  render(<CaseProvenanceView value={{caseId:1,caseKey:"demo-1",isDemo:true,sourceRecordKey:"invoice-1",generatorVersion:"support-v3",generatorSeed:2026,fieldLineage:{product:{provenance:"observed",source_field:"description"},cancellationReason:{provenance:"synthetic",method:"unavailable"}},dataSource:{id:1,datasetKey:"uci",version:"2026-08",title:"UCI Online Retail II",publisher:"UCI",sourceUri:"https://archive.ics.uci.edu/",license:"CC BY 4.0",limitations:["无取消原因字段"]}}}/>);
  expect(screen.getByText("DEMO 场景")).toBeInTheDocument();
  expect(screen.getByText(/数据版本 2026-08/)).toBeInTheDocument();
  expect(screen.getByText(/cancellationReason: synthetic（不可用）/)).toBeInTheDocument();
  expect(screen.getByRole("link", {name:/查看来源说明/})).toHaveAttribute("href", "https://archive.ics.uci.edu/");
}));

it("describes an authorized local source without exposing its private URI as a link", () => {
  const { container } = render(<CaseProvenanceView value={{caseId:2,caseKey:"local-1",isDemo:false,sourceRecordKey:"order-1",generatorVersion:"support-v3",generatorSeed:2026,fieldLineage:{product:{provenance:"observed",source_field:"GoodsOrder.csv"}},dataSource:{id:2,datasetKey:"authorized-local",version:"2026-08",title:"Local goods data",publisher:"Local authorized files",sourceUri:"user-authorized-local://GoodsOrder.csv+GoodsTypes.csv",license:"User authorized",limitations:[]}}}/>);
  const view = within(container);

  expect(view.queryByRole("link", {name:/查看来源说明/})).not.toBeInTheDocument();
  expect(view.getByText(/本地授权来源.*GoodsOrder\.csv.*GoodsTypes\.csv/)).toBeInTheDocument();
  expect(view.getByText(/原始文件不随系统部署.*无法网页预览/)).toBeInTheDocument();
});

it("describes another private source without exposing it as a browser link", () => {
  const { container } = render(<CaseProvenanceView value={{caseId:3,caseKey:"internal-1",isDemo:false,sourceRecordKey:"case-1",generatorVersion:"support-v3",generatorSeed:2026,fieldLineage:{product:{provenance:"observed",source_field:"description"}},dataSource:{id:3,datasetKey:"internal",version:"2026-08",title:"Internal support data",publisher:"Support",sourceUri:"internal-dataset://support/cases",license:"Internal",limitations:[]}}}/>);
  const view = within(container);

  expect(view.queryByRole("link", {name:/查看来源说明/})).not.toBeInTheDocument();
  expect(view.getByText(/内部来源.*无法通过网页打开/)).toBeInTheDocument();
});
