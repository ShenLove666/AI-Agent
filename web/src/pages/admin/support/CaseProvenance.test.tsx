import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CaseProvenanceView } from "./CaseProvenanceView";

describe("CaseProvenance", () => it("shows source version, generator and unavailable fields", () => {
  render(<CaseProvenanceView value={{caseId:1,caseKey:"demo-1",isDemo:true,sourceRecordKey:"invoice-1",generatorVersion:"support-v3",generatorSeed:2026,fieldLineage:{product:{provenance:"observed",source_field:"description"},cancellationReason:{provenance:"synthetic",method:"unavailable"}},dataSource:{id:1,datasetKey:"uci",version:"2026-08",title:"UCI Online Retail II",publisher:"UCI",sourceUri:"https://archive.ics.uci.edu/",license:"CC BY 4.0",limitations:["无取消原因字段"]}}}/>);
  expect(screen.getByText("DEMO 场景")).toBeInTheDocument();
  expect(screen.getByText(/数据版本 2026-08/)).toBeInTheDocument();
  expect(screen.getByText(/cancellationReason: synthetic（不可用）/)).toBeInTheDocument();
  expect(screen.getByRole("link", {name:/查看来源说明/})).toHaveAttribute("href", "https://archive.ics.uci.edu/");
}));
