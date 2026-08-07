import { api } from "@/services/api";

export type CaseStatus = "pending" | "in_progress" | "resolved" | "escalated";
export type CasePriority = "low" | "normal" | "high" | "urgent";
export interface SupportCaseSummary { id:number; caseKey:string; customerName:string; channel:string; subject:string; status:CaseStatus; priority:CasePriority; assigneeId:number|null; labels:string[]; unread:boolean; version:number; isDemo:boolean; lastMessage:string|null; updatedAt:string; }
export interface SupportSuggestion { id:number; status:string; content:string|null; citations:Array<{title?:string;content?:string;releaseVersion?:string;documentId?:number}>; riskFlags:string[]; modelId:string; promptVersion:string; knowledgeReleaseId:number|null; latencyMs:number|null; errorCode:string|null; decision:string|null; finalContent:string|null; createdAt:string; }
export interface SupportCaseDetail extends SupportCaseSummary { resolutionCode:string|null; resolutionNote:string|null; messages:Array<{id:number;role:"customer"|"agent"|"system";content:string;sentToCustomer:boolean;suggestionId:number|null;createdAt:string}>; events:Array<{id:number;type:string;payload:Record<string,unknown>;occurredAt:string}>; suggestions:SupportSuggestion[]; }
export interface SupportMetrics { totalCases:number; pendingCases:number; resolvedCases:number; escalatedCases:number; resolutionRate:number|null; acceptanceRate:number|null; editRate:number|null; citationCoverage:number|null; provenance:"demo"|"mixed"|"production"; }
export interface KnowledgeRelease { id:number; version:string; title:string; status:string; processingStatus:string; retrievalMode:string; isActive:boolean; isDemo:boolean; contentHash:string; publishedAt:string|null; documents:Array<{id:number;filename:string;hash:string}>; }
export interface KnowledgeGap { id:number; title:string; category:string; severity:string; status:string; occurrenceCount:number; ownerUserId:number|null; resolvingReleaseId:number|null; evidence:Array<Record<string,unknown>>; isDemo:boolean; }
export interface QualityOverview { reviewed:number; passed:number; failureCategories:Record<string,number>; openGaps:number; gaps:KnowledgeGap[]; provenance:string; }
export interface EvaluationRun { id:number; status:string; score:number|null; caseCount:number; highRiskFailures:number; gate:"passed"|"blocked"; startedAt:string; isDemo:boolean; }
export interface EvaluationOverview { datasetCount:number; evaluationCaseCount:number; runs:EvaluationRun[]; provenance:string; }

export const getSupportCases = (params:Record<string,unknown>={}) => api.get<never,SupportCaseSummary[]>("/support/cases",{params});
export const getSupportCase = (id:number) => api.get<never,SupportCaseDetail>(`/support/cases/${id}`);
export const getSupportMetrics = () => api.get<never,SupportMetrics>("/support/metrics");
export const assignSupportCase = (id:number,assigneeId:number|null,expectedVersion:number) => api.post<never,SupportCaseDetail>(`/support/cases/${id}/assign`,{assigneeId,expectedVersion});
export const transitionSupportCase = (id:number,status:CaseStatus,expectedVersion:number,extra:Record<string,unknown>={}) => api.post<never,SupportCaseDetail>(`/support/cases/${id}/transition`,{status,expectedVersion,...extra});
export const sendManualReply = (id:number,content:string) => api.post<never,SupportCaseDetail>(`/support/cases/${id}/replies`,{content});
export const generateSupportSuggestion = (id:number) => api.post<never,SupportSuggestion>(`/support/cases/${id}/suggestions`);
export const decideSupportSuggestion = (caseId:number,suggestionId:number,decision:string,finalContent?:string,reason?:string) => api.post<never,SupportCaseDetail>(`/support/cases/${caseId}/suggestions/${suggestionId}/decision`,{decision,finalContent,reason});
export const getKnowledgeReleases = () => api.get<never,KnowledgeRelease[]>("/support/knowledge/releases");
export const publishKnowledgeRelease = (id:number) => api.post<never,KnowledgeRelease>(`/support/knowledge/releases/${id}/publish`);
export const activateKnowledgeRelease = (id:number) => api.post<never,KnowledgeRelease>(`/support/knowledge/releases/${id}/activate`);
export const getQualityOverview = () => api.get<never,QualityOverview>("/support/quality");
export const resolveKnowledgeGap = (gapId:number,releaseId:number) => api.post<never,KnowledgeGap>(`/support/quality/gaps/${gapId}/resolve`,{releaseId});
export const getEvaluationOverview = () => api.get<never,EvaluationOverview>("/support/evaluations");
export const runSupportEvaluation = (releaseId:number) => api.post<never,EvaluationRun>("/support/evaluations",{releaseId});
export const decideKnowledgeRelease = (runId:number,releaseId:number,decision:"approved"|"rejected") => api.post("/support/release-decisions",{runId,releaseId,decision});
