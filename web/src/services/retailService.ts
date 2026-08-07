import { api } from "@/services/api";

export type RetailMetric = { key: string; label: string; value: number | null; numerator: number; denominator: number; unit: string; dataState: string; origin: "synthetic" };
export type RetailRule = { id: number; from: string; to: string; count: number; support: number; confidence: number; lift: number; evidence: string[]; origin: "source" };
export type RetailOverview = {
  ready: boolean;
  dataState: "ready" | "empty";
  profile: null | { name: string; businessType: string; storeCount: number; goal: string; stage: string };
  checklist?: Array<{ key: string; label: string; done: boolean; optional?: boolean }>;
  summary: null | { orders: number; rows: number; products: number; averageBasketSize: number; rules: number; sourceFingerprint: string; origin: "source" };
  rules: RetailRule[];
  campaigns: Array<{ id: number; name: string; status: string; version: number }>;
  metrics: RetailMetric[];
  tasks: Array<{ id: number; title: string; status: string; targetMetric?: string }>;
  evaluations: Array<{ id: number; status: string; startedAt: string; isDemo: boolean }>;
};

export const getRetailOverview = () => api.get<RetailOverview, RetailOverview>("/retail/overview");
export const createRetailCampaign = (ruleId: number) => api.post("/retail/campaigns", { ruleId });
export const transitionRetailTask = (taskId: number, status: string) => api.post(`/retail/optimization-tasks/${taskId}/transition`, { status });
export const getRetailReport = () => api.get<{ filename: string; content: string }, { filename: string; content: string }>("/retail/reports/weekly");
