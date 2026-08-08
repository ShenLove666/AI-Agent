import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RetailOperationsPage } from "./RetailOperationsPage";

vi.mock("@/services/retailService", () => ({
  getRetailOverview: vi.fn().mockResolvedValue({ready:true,dataState:"ready",profile:{name:"邻里鲜选",businessType:"即时零售",storeCount:0,goal:"提升连带",stage:"demo"},summary:{orders:100,rows:300,products:20,averageBasketSize:3,rules:1,sources:1,sourceFingerprint:"abc",origin:"observed+derived"},rules:[{id:1,from:"牛奶",to:"面包",count:20,support:.2,confidence:.4,lift:1.8,evidence:["20 baskets"],origin:"derived"}],campaigns:[],metrics:[{key:"acceptance",label:"建议采用率",value:80,numerator:8,denominator:10,unit:"%",dataState:"demo",origin:"synthetic"}],tasks:[],evaluations:[]}),
  getRetailDataSources: vi.fn().mockResolvedValue([{id:1,datasetKey:"uci",version:"v1",title:"真实零售快照",sourceKind:"public",sourceUri:"https://example.com",publisher:"UCI",license:"CC BY",retrievedAt:"2026-08-01",encoding:"utf-8",transformVersion:"v2",manifestSha256:"a".repeat(64),limitations:[],counts:{orders:100},acceptedRows:300,rejectedRows:0,isDemo:true}]),
  getRetailDataSourceQuality: vi.fn(),createRetailCampaign:vi.fn(),transitionRetailTask:vi.fn(),getRetailReport:vi.fn()
}));

describe("RetailOperations", () => it("labels observed, derived and synthetic populations", async () => {
  render(<RetailOperationsPage/>);
  expect(await screen.findByText("真实零售快照")).toBeInTheDocument();
  expect(screen.getAllByText("真实观测数据").length).toBeGreaterThan(0);
  expect(screen.getAllByText("可复算衍生指标").length).toBeGreaterThan(0);
  expect(screen.getAllByText("模拟运营数据").length).toBeGreaterThan(0);
  expect(screen.getByText("转换 v2")).toBeInTheDocument();
}));
