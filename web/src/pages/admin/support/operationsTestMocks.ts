import { vi } from "vitest";

export const release = {
  id: 1,
  version: "support-v1",
  title: "售后政策",
  status: "published",
  processingStatus: "ready",
  retrievalMode: "keyword",
  isActive: true,
  isDemo: true,
  contentHash: "a".repeat(64),
  publishedAt: "2026-08-07T00:00:00",
  documents: [{ id: 1, filename: "refund.md", hash: "b".repeat(64) }]
};
export const quality = {
  reviewed: 12,
  passed: 9,
  failureCategories: { missing_policy: 3 },
  openGaps: 1,
  provenance: "demo",
  gaps: [
    {
      id: 1,
      title: "优惠券返还时效缺失",
      category: "missing_policy",
      severity: "high",
      status: "open",
      occurrenceCount: 4,
      ownerUserId: null,
      resolvingReleaseId: null,
      evidence: [{ caseId: 1 }],
      isDemo: true
    }
  ]
};
export const evaluation = {
  datasetCount: 1,
  evaluationCaseCount: 14,
  provenance: "demo",
  runs: [
    {
      id: 1,
      status: "completed",
      score: 92,
      caseCount: 14,
      highRiskFailures: 0,
      gate: "passed",
      startedAt: "2026-08-07T00:00:00",
      isDemo: true
    }
  ]
};

export const supportOperationsMocks = {
  getKnowledgeReleases: vi.fn().mockResolvedValue([release]),
  getKnowledgeSources: vi.fn().mockResolvedValue([]),
  getQualityOverview: vi.fn().mockResolvedValue(quality),
  getEvaluationOverview: vi.fn().mockResolvedValue(evaluation),
  getSupportCoverage: vi.fn().mockResolvedValue({totalCases:16,categories:{refund:8},statuses:{resolved:9},sourceVersions:{"retail-v1":12},demoCases:12,ordinaryCases:4,provenance:"mixed",unsupportedSegments:[]}),
  activateKnowledgeRelease: vi.fn(),
  decideKnowledgeRelease: vi.fn(),
  resolveKnowledgeGap: vi.fn(),
  runSupportEvaluation: vi.fn()
};
