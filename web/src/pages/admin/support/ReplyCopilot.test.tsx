import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupportWorkbenchPage } from "./SupportWorkbenchPage";

vi.mock("@/services/supportService",()=>({
 getSupportCases:vi.fn().mockResolvedValue([{id:3,caseKey:"demo-3",customerName:"顾客",channel:"web",subject:"退款咨询",status:"pending",priority:"urgent",assigneeId:null,labels:["refund"],unread:true,version:1,isDemo:true,lastMessage:"优惠券会退吗",updatedAt:"2026-08-07T00:00:00"}]),
 getSupportMetrics:vi.fn().mockResolvedValue({totalCases:1,pendingCases:1,resolvedCases:0,escalatedCases:0,resolutionRate:0,acceptanceRate:null,editRate:null,citationCoverage:100,provenance:"demo"}),
 getSupportCase:vi.fn().mockResolvedValue({id:3,caseKey:"demo-3",customerName:"顾客",channel:"web",subject:"退款咨询",status:"pending",priority:"urgent",assigneeId:null,labels:["refund"],unread:true,version:1,isDemo:true,lastMessage:"优惠券会退吗",updatedAt:"2026-08-07T00:00:00",resolutionCode:null,resolutionNote:null,messages:[{id:3,role:"customer",content:"优惠券会退吗",sentToCustomer:false,suggestionId:null,createdAt:"2026-08-07T00:00:00"}],events:[],suggestions:[{id:7,status:"completed",content:"请保留凭证申请售后。",citations:[{content:"优惠券按活动规则返还",releaseVersion:"v1"}],riskFlags:["refund_review"],modelId:"deepseek-flash",promptVersion:"support-v1",knowledgeReleaseId:1,latencyMs:620,errorCode:null,decision:null,finalContent:null,createdAt:"2026-08-07T00:00:00"}]}),
 assignSupportCase:vi.fn(),transitionSupportCase:vi.fn(),sendManualReply:vi.fn(),generateSupportSuggestion:vi.fn(),decideSupportSuggestion:vi.fn()
}));

describe("ReplyCopilot",()=>{it("shows evidence and human review controls",async()=>{render(<SupportWorkbenchPage/>);expect(await screen.findByText("引用证据 · 1")).toBeInTheDocument();expect(screen.getByText("优惠券按活动规则返还")).toBeInTheDocument();expect(screen.getByRole("button",{name:"采纳并发送"})).toBeInTheDocument();expect(screen.getByRole("button",{name:"升级主管"})).toBeInTheDocument()})});
