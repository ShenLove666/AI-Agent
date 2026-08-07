import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SupportWorkbenchPage } from "./SupportWorkbenchPage";

vi.mock("@/services/supportService",()=>({
 getSupportCases:vi.fn().mockResolvedValue([{id:2,caseKey:"demo-2",customerName:"周先生",channel:"app",subject:"配送超时处理",status:"in_progress",priority:"high",assigneeId:1,labels:["delivery"],unread:false,version:2,isDemo:true,lastMessage:"订单迟到了",updatedAt:"2026-08-07T00:00:00"}]),
 getSupportMetrics:vi.fn().mockResolvedValue({totalCases:1,pendingCases:0,resolvedCases:0,escalatedCases:0,resolutionRate:0,acceptanceRate:null,editRate:null,citationCoverage:null,provenance:"demo"}),
 getSupportCase:vi.fn().mockResolvedValue({id:2,caseKey:"demo-2",customerName:"周先生",channel:"app",subject:"配送超时处理",status:"in_progress",priority:"high",assigneeId:1,labels:["delivery"],unread:false,version:2,isDemo:true,lastMessage:"订单迟到了",updatedAt:"2026-08-07T00:00:00",resolutionCode:null,resolutionNote:null,messages:[{id:2,role:"customer",content:"订单迟到了",sentToCustomer:false,suggestionId:null,createdAt:"2026-08-07T00:00:00"}],events:[],suggestions:[]}),
 assignSupportCase:vi.fn(),transitionSupportCase:vi.fn(),sendManualReply:vi.fn(),generateSupportSuggestion:vi.fn(),decideSupportSuggestion:vi.fn()
}));

describe("CaseWorkspace",()=>{it("keeps manual handling available",async()=>{render(<SupportWorkbenchPage/>);expect(await screen.findByText("订单迟到了")).toBeInTheDocument();expect(screen.getByPlaceholderText("输入人工回复，或使用右侧 AI 建议…")).toBeInTheDocument();expect(screen.getByRole("button",{name:/解决/})).toBeInTheDocument()})});
