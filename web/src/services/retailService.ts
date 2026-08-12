import { api } from "@/services/api";

export type RetailMetric = {
  key: string;
  label: string;
  value: number | null;
  numerator: number;
  denominator: number;
  unit: string;
  dataState: string;
  origin: "synthetic";
};
export type RetailDataSource = {
  id: number;
  datasetKey: string;
  version: string;
  title: string;
  sourceKind: string;
  sourceUri: string;
  publisher: string;
  license: string;
  retrievedAt: string;
  encoding: string;
  transformVersion: string;
  manifestSha256: string;
  limitations: string[];
  counts: Record<string, number>;
  acceptedRows: number;
  rejectedRows: number;
  isDemo: boolean;
};
export type RetailDataSourceQuality = {
  id: number;
  datasetKey: string;
  version: string;
  schema: Record<string, unknown>;
  counts: Record<string, number>;
  acceptedRows: number;
  rejectedRows: number;
  limitations: string[];
  selectionRules: string[];
  transformVersion: string;
  manifestSha256: string;
  provenance: "observed";
};
export type RetailDataSourcePreview = {
  datasetId: number;
  datasetKey: string;
  title?: string;
  products: Array<{ name: string; category: string; provenance: string }>;
  baskets: Array<{
    basketKey: string;
    country: string | null;
    status: string | null;
    items: Array<{ product: string; quantity: number; unitPrice: number | null }>;
  }>;
};
export type RetailRule = {
  id: number;
  from: string;
  to: string;
  count: number;
  support: number;
  confidence: number;
  lift: number;
  evidence: string[];
  origin: "derived";
};
export type RetailCampaign = {
  id: number;
  name: string;
  status: string;
  version: number;
  rule?: null | {
    from: string;
    to: string;
    count: number;
    support: number;
    confidence: number;
    lift: number;
    evidence: string[];
  };
};
export type RetailCampaignDetail = {
  id: number;
  name: string;
  status: string;
  version: number;
  lockVersion: number;
  rejectedReason: string | null;
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
  rule: null | {
    id: number;
    count: number;
    support: number;
    confidence: number;
    lift: number;
    evidence: string[];
    origin: "derived";
  };
  versions: Array<{
    version: number;
    channel: string;
    copy: string;
    ruleSnapshot: Record<string, number | string>;
    approvedBy: number | null;
    approvedAt: string | null;
    createdAt: string;
  }>;
  task: null | { id: number; title: string; status: string };
};
export type RetailTask = {
  id: number;
  title: string;
  status: string;
  targetMetric?: string;
  sourceType?: string;
  sourceId?: string;
  assigneeId?: number | null;
  verificationRunId?: number | null;
  verificationRunStatus?: string | null;
  changeVersion?: string | null;
  createdAt?: string;
};
export type RetailTaskDetail = {
  id: number;
  sourceType: string;
  sourceId: string;
  title: string;
  status: string;
  assigneeId: number | null;
  targetMetric: string | null;
  changeVersion: string | null;
  verificationRunId: number | null;
  beforeEvidence: Record<string, unknown>;
  afterEvidence: Record<string, unknown>;
  associationRuleId: number | null;
  supportCaseId: number | null;
  isDemo: boolean;
  createdAt: string;
  updatedAt: string;
  verificationRun: null | {
    id: number;
    status: string;
    startedAt: string;
    completedAt: string | null;
    isDemo: boolean;
  };
};
export type RetailOverview = {
  ready: boolean;
  dataState: "ready" | "empty";
  profile: null | {
    name: string;
    businessType: string;
    storeCount: number;
    goal: string;
    stage: string;
  };
  checklist?: Array<{ key: string; label: string; done: boolean; optional?: boolean }>;
  summary: null | {
    orders: number;
    rows: number;
    products: number;
    averageBasketSize: number;
    rules: number;
    sources: number;
    sourceFingerprint: string;
    origin: "observed+derived";
  };
  rules: RetailRule[];
  campaigns: RetailCampaign[];
  metrics: RetailMetric[];
  tasks: RetailTask[];
  evaluations: Array<{ id: number; status: string; startedAt: string; isDemo: boolean }>;
};

export const getRetailOverview = () => api.get<RetailOverview, RetailOverview>("/retail/overview");
export const getRetailDataSources = () =>
  api.get<RetailDataSource[], RetailDataSource[]>("/retail/data-sources");
export const getRetailDataSourceQuality = (id: number) =>
  api.get<never, RetailDataSourceQuality>(`/data-sources/${id}/quality`);
export const getRetailDataSourcePreview = (id: number) =>
  api.get<never, RetailDataSourcePreview>(`/data-sources/${id}/preview`);
export const createRetailCampaign = (ruleId: number) => api.post("/retail/campaigns", { ruleId });
export const getRetailCampaign = (campaignId: number) =>
  api.get<never, RetailCampaignDetail>(`/retail/campaigns/${campaignId}`);
export const transitionRetailCampaign = (
  campaignId: number,
  action: "confirm" | "reject" | "publish",
  expectedVersion: number,
  reason?: string
) =>
  api.post(`/retail/campaigns/${campaignId}/transition`, {
    action,
    expectedVersion,
    reason
  });
export const transitionRetailTask = (taskId: number, status: string, changeVersion?: string) =>
  api.post(`/retail/optimization-tasks/${taskId}/transition`, { status, changeVersion });
export const getRetailTask = (taskId: number) =>
  api.get<never, RetailTaskDetail>(`/retail/optimization-tasks/${taskId}`);
export const assignRetailTask = (taskId: number, assigneeId: number | null) =>
  api.post(`/retail/optimization-tasks/${taskId}/assign`, { assigneeId });
export const verifyRetailTask = (taskId: number) =>
  api.post(`/retail/optimization-tasks/${taskId}/verify`);
export const syncFailedEvaluations = () =>
  api.post<never, { created: number }>("/retail/optimization-tasks/sync-from-evaluations");
export const getRetailReport = () =>
  api.get<{ filename: string; content: string }, { filename: string; content: string }>(
    "/retail/reports/weekly"
  );
