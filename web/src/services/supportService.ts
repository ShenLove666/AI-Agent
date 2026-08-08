import { api } from "@/services/api";

export type CaseStatus = "pending" | "in_progress" | "resolved" | "escalated";
export type CasePriority = "low" | "normal" | "high" | "urgent";
export interface SupportCaseSummary {
  id: number;
  caseKey: string;
  customerName: string;
  channel: string;
  subject: string;
  status: CaseStatus;
  priority: CasePriority;
  assigneeId: number | null;
  labels: string[];
  unread: boolean;
  version: number;
  isDemo: boolean;
  lastMessage: string | null;
  updatedAt: string;
}
export interface SupportSuggestion {
  id: number;
  status: string;
  content: string | null;
  citations: Array<{
    docName?: string;
    content?: string;
    excerpt?: string;
    releaseVersion?: string;
    documentId?: number;
    canonicalUrl?: string | null;
    publisher?: string | null;
    retrievedAt?: string | null;
    applicability?: string[];
    exclusions?: string[];
    reviewStatus?: string;
  }>;
  riskFlags: string[];
  modelId: string;
  promptVersion: string;
  knowledgeReleaseId: number | null;
  latencyMs: number | null;
  errorCode: string | null;
  decision: string | null;
  finalContent: string | null;
  createdAt: string;
}
export interface SupportCaseDetail extends SupportCaseSummary {
  resolutionCode: string | null;
  resolutionNote: string | null;
  provenance: {
    sourceRecordKey: string | null;
    generatorVersion: string | null;
    generatorSeed: number | null;
    fieldLineage: Record<
      string,
      { provenance: "observed" | "derived" | "synthetic"; source_field?: string; method?: string }
    >;
    dataSource: null | {
      id: number;
      datasetKey: string;
      version: string;
      title: string;
      publisher: string;
      sourceUri: string;
      license: string;
      limitations: string[];
    };
  };
  messages: Array<{
    id: number;
    role: "customer" | "agent" | "system";
    content: string;
    sentToCustomer: boolean;
    suggestionId: number | null;
    createdAt: string;
  }>;
  events: Array<{ id: number; type: string; payload: Record<string, unknown>; occurredAt: string }>;
  suggestions: SupportSuggestion[];
}
export interface SupportOrderContext {
  id: number;
  orderNo: string;
  status: string;
  amount: { currency: string; minor: number };
  placedAt: string | null;
  isDemo: boolean;
  provenance: "observed" | "synthetic";
  lineage: Record<string, unknown>;
  items: Array<{
    id: number;
    sku: string;
    productId: number | null;
    productName: string;
    quantity: number;
    unitPriceMinor: number;
    lineage: Record<string, unknown>;
  }>;
  fulfillment: null | {
    id: number;
    status: string;
    carrier: string | null;
    trackingNo: string | null;
    estimatedDeliveryAt: string | null;
    deliveredAt: string | null;
    currentLocation: string | null;
    delayMinutes: number | null;
    delayProvenance: "derived" | "unavailable";
    updatedAt: string;
    lineage: Record<string, unknown>;
  };
  refund: null | {
    id: number;
    status: string;
    amountMinor: number;
    reason: string | null;
    requestedAt: string | null;
    resolvedAt: string | null;
    lineage: Record<string, unknown>;
  };
  customer: null | {
    id: number;
    customerKey: string;
    displayName: string;
    tier: string;
    orderCount: number;
    refundCount: number;
    lifetimeValueMinor: number;
    capturedAt: string;
    isDemo: boolean;
    lineage: Record<string, unknown>;
  };
}
export interface SupportWorkspace {
  case: SupportCaseSummary;
  order: SupportOrderContext | null;
  activeSuggestion: SupportSuggestion | null;
  outboundMessages: Array<{
    id: number;
    channel: string;
    status: string;
    externalId: string | null;
    failureReason: string | null;
    isDemo: boolean;
    deliveryClaim: "simulated" | "external-status";
    createdAt: string;
    sentAt: string | null;
    deliveredAt: string | null;
  }>;
  diagnostics: { messageCount: number; suggestionCount: number; outboundCount: number };
}
export type CaseProvenance = SupportCaseDetail["provenance"] & {
  caseId: number;
  caseKey: string;
  isDemo: boolean;
};
export interface SupportCoverage {
  totalCases: number;
  categories: Record<string, number>;
  statuses: Record<string, number>;
  sourceVersions: Record<string, number>;
  demoCases: number;
  ordinaryCases: number;
  provenance: "demo" | "mixed" | "production";
  unsupportedSegments: string[];
}
export interface SupportMetrics {
  totalCases: number;
  pendingCases: number;
  resolvedCases: number;
  escalatedCases: number;
  resolutionRate: number | null;
  acceptanceRate: number | null;
  editRate: number | null;
  citationCoverage: number | null;
  provenance: "demo" | "mixed" | "production";
}
export interface KnowledgeRelease {
  id: number;
  version: string;
  title: string;
  status: string;
  processingStatus: string;
  retrievalMode: string;
  isActive: boolean;
  isDemo: boolean;
  contentHash: string;
  publishedAt: string | null;
  documents: Array<{ id: number; filename: string; hash: string }>;
}
export interface KnowledgeSource {
  id: number;
  title: string;
  filename: string;
  contentOrigin: "public_summary" | "synthetic" | "user_upload";
  publisher: string | null;
  canonicalUrl: string | null;
  retrievedAt: string | null;
  jurisdiction: string | null;
  nextReviewAt: string | null;
  reviewStatus: string;
  applicability: string[];
  exclusions: string[];
  usageNote: string | null;
  status: string;
  enabled: boolean;
  checksum: string | null;
}
export interface KnowledgeGap {
  id: number;
  title: string;
  category: string;
  severity: string;
  status: string;
  occurrenceCount: number;
  ownerUserId: number | null;
  resolvingReleaseId: number | null;
  evidence: Array<Record<string, unknown>>;
  isDemo: boolean;
}
export interface QualityOverview {
  reviewed: number;
  passed: number;
  failureCategories: Record<string, number>;
  openGaps: number;
  gaps: KnowledgeGap[];
  provenance: string;
}
export interface EvaluationRun {
  id: number;
  status: string;
  score: number | null;
  caseCount: number;
  highRiskFailures: number;
  gate: "passed" | "blocked";
  startedAt: string;
  isDemo: boolean;
}
export interface EvaluationOverview {
  datasetCount: number;
  evaluationCaseCount: number;
  runs: EvaluationRun[];
  provenance: string;
}

export const getSupportCases = (params: Record<string, unknown> = {}) =>
  api.get<never, SupportCaseSummary[]>("/support/cases", { params });
export const getSupportCase = (id: number) =>
  api.get<never, SupportCaseDetail>(`/support/cases/${id}`);
export const getSupportWorkspace = (id: number) =>
  api.get<never, SupportWorkspace>(`/support/cases/${id}/workspace`);
export const getCaseProvenance = (id: number) =>
  api.get<never, CaseProvenance>(`/support/cases/${id}/provenance`);
export const getSupportCoverage = () => api.get<never, SupportCoverage>("/support/coverage");
export const getSupportMetrics = () => api.get<never, SupportMetrics>("/support/metrics");
export const assignSupportCase = (id: number, assigneeId: number | null, expectedVersion: number) =>
  api.post<never, SupportCaseDetail>(`/support/cases/${id}/assign`, {
    assigneeId,
    expectedVersion
  });
export const transitionSupportCase = (
  id: number,
  status: CaseStatus,
  expectedVersion: number,
  extra: Record<string, unknown> = {}
) =>
  api.post<never, SupportCaseDetail>(`/support/cases/${id}/transition`, {
    status,
    expectedVersion,
    ...extra
  });
export const sendManualReply = (id: number, content: string) =>
  api.post<never, SupportCaseDetail>(`/support/cases/${id}/replies`, { content });
export const generateSupportSuggestion = (id: number) =>
  api.post<never, SupportSuggestion>(`/support/cases/${id}/suggestions`);
export const decideSupportSuggestion = (
  caseId: number,
  suggestionId: number,
  decision: string,
  finalContent?: string,
  reason?: string
) =>
  api.post<never, SupportCaseDetail>(
    `/support/cases/${caseId}/suggestions/${suggestionId}/decision`,
    { decision, finalContent, reason }
  );
export const getKnowledgeReleases = () =>
  api.get<never, KnowledgeRelease[]>("/support/knowledge/releases");
export const getKnowledgeSources = () =>
  api.get<never, KnowledgeSource[]>("/support/knowledge/sources");
export const publishKnowledgeRelease = (id: number) =>
  api.post<never, KnowledgeRelease>(`/support/knowledge/releases/${id}/publish`);
export const activateKnowledgeRelease = (id: number) =>
  api.post<never, KnowledgeRelease>(`/support/knowledge/releases/${id}/activate`);
export const getQualityOverview = () => api.get<never, QualityOverview>("/support/quality");
export const resolveKnowledgeGap = (gapId: number, releaseId: number) =>
  api.post<never, KnowledgeGap>(`/support/quality/gaps/${gapId}/resolve`, { releaseId });
export const getEvaluationOverview = () =>
  api.get<never, EvaluationOverview>("/support/evaluations");
export const runSupportEvaluation = (releaseId: number) =>
  api.post<never, EvaluationRun>("/support/evaluations", { releaseId });
export const decideKnowledgeRelease = (
  runId: number,
  releaseId: number,
  decision: "approved" | "rejected"
) => api.post("/support/release-decisions", { runId, releaseId, decision });
