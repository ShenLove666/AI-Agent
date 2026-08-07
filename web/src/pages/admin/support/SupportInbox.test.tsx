import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupportWorkbenchPage } from "./SupportWorkbenchPage";

vi.mock("@/services/supportService",()=>({
  getSupportCases:vi.fn().mockResolvedValue([{id:1,caseKey:"demo-1",customerName:"林女士",channel:"web",subject:"草莓破损退款",status:"pending",priority:"urgent",assigneeId:null,labels:["refund"],unread:true,version:1,isDemo:true,lastMessage:"草莓坏了",updatedAt:"2026-08-07T00:00:00"}]),
  getSupportMetrics:vi.fn().mockResolvedValue({totalCases:36,pendingCases:9,resolvedCases:9,escalatedCases:9,resolutionRate:25,acceptanceRate:75,editRate:25,citationCoverage:100,provenance:"demo"}),
  getSupportCase:vi.fn().mockResolvedValue({id:1,caseKey:"demo-1",customerName:"林女士",channel:"web",subject:"草莓破损退款",status:"pending",priority:"urgent",assigneeId:null,labels:["refund"],unread:true,version:1,isDemo:true,lastMessage:"草莓坏了",updatedAt:"2026-08-07T00:00:00",resolutionCode:null,resolutionNote:null,messages:[{id:1,role:"customer",content:"草莓坏了",sentToCustomer:false,suggestionId:null,createdAt:"2026-08-07T00:00:00"}],events:[],suggestions:[]}),
  assignSupportCase:vi.fn(),transitionSupportCase:vi.fn(),sendManualReply:vi.fn(),generateSupportSuggestion:vi.fn(),decideSupportSuggestion:vi.fn()
}));

describe("SupportInbox",()=>{it("renders an actionable merchant queue",async()=>{render(<SupportWorkbenchPage/>);expect((await screen.findAllByText("草莓破损退款")).length).toBeGreaterThan(0);expect(screen.getByText("工单队列")).toBeInTheDocument();expect(screen.getByText("演示数据 · 指标由工单事件计算")).toBeInTheDocument()})});
