import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KnowledgeSourcesView } from "./KnowledgeSourcesView";

describe("KnowledgeSources", () => it("separates official summaries from demo SOP and exposes freshness", () => {
  render(<KnowledgeSourcesView sources={[{id:1,title:"七日无理由退货规则摘要",filename:"refund.md",contentOrigin:"public_summary",publisher:"国家市场监督管理总局",canonicalUrl:"https://www.samr.gov.cn/",retrievedAt:"2026-08-01",jurisdiction:"中国大陆",nextReviewAt:"2026-11-01",reviewStatus:"current",applicability:["网络零售"],exclusions:["定制商品"],usageNote:"仅作公开规则摘要",status:"parsed",enabled:true,checksum:"a".repeat(64)},{id:2,title:"鲜配商家退款 SOP",filename:"sop.md",contentOrigin:"synthetic",publisher:null,canonicalUrl:null,retrievedAt:null,jurisdiction:null,nextReviewAt:null,reviewStatus:"current",applicability:["演示店铺"],exclusions:[],usageNote:"虚构 SOP",status:"parsed",enabled:true,checksum:"b".repeat(64)}]}/>);
  expect(screen.getByText("官方来源摘要")).toBeInTheDocument();
  expect(screen.getByText("演示知识")).toBeInTheDocument();
  expect(screen.getByText(/下次复核 2026-11-01/)).toBeInTheDocument();
  expect(screen.getByRole("link", {name:/查看权威原文/})).toHaveAttribute("href", "https://www.samr.gov.cn/");
  expect(screen.getByText(/无外部链接/)).toBeInTheDocument();
}));
