import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DataSourcesView } from "./DataSourcesView";

vi.mock("@/services/retailService", () => ({
  getRetailDataSources: vi.fn().mockResolvedValue([{id:1,datasetKey:"uci",version:"2026-08",title:"UCI Online Retail II",sourceKind:"public",sourceUri:"https://archive.ics.uci.edu/dataset/502/online+retail+ii",publisher:"UCI",license:"CC BY 4.0",retrievedAt:"2026-08-01T00:00:00",encoding:"utf-8",transformVersion:"retail-normalizer-v2",manifestSha256:"a".repeat(64),limitations:["未提供商品分类"],counts:{orders:100},acceptedRows:500,rejectedRows:2,isDemo:true}]),
  getRetailDataSourceQuality: vi.fn().mockResolvedValue({id:1,datasetKey:"uci",version:"2026-08",schema:{},counts:{orders:100},acceptedRows:500,rejectedRows:2,limitations:["未提供商品分类"],selectionRules:["仅保留英国交易"],transformVersion:"retail-normalizer-v2",manifestSha256:"a".repeat(64),provenance:"observed"})
}));

describe("DataSources", () => it("shows demo provenance, source link, limitations and quality detail", async () => {
  render(<DataSourcesView/>);
  expect(await screen.findByText("UCI Online Retail II")).toBeInTheDocument();
  expect(screen.getByText("DEMO 数据")).toBeInTheDocument();
  expect(screen.getByRole("link", {name:/原始来源/})).toHaveAttribute("href", expect.stringContaining("archive.ics.uci.edu"));
  fireEvent.click(screen.getByRole("button", {name:"查看质量"}));
  expect(await screen.findByRole("dialog", {name:"数据质量详情"})).toHaveTextContent("仅保留英国交易");
  expect(screen.getByRole("dialog")).toHaveTextContent("未提供商品分类");
}));
