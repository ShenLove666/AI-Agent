import { describe, expect, it } from "vitest";

import {
  cancelAgentSteps,
  computeAgentExecutionSummary,
  restoreAgentExecution
} from "./agentExecution";

describe("restoreAgentExecution", () => {
  it("restores a tool row from persisted {label, toolKey} (no name)", () => {
    const json = {
      summary: { planCount: 1, toolCallCount: 1, evidenceCount: 2, replanCount: 0 },
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" },
        {
          seq: 2,
          phase: "tool",
          status: "completed",
          plan: 1,
          title: "业务数据查询",
          tool: { label: "购物篮关联规则", toolKey: "commerce_search_association_rules" }
        },
        { seq: 3, phase: "generation", status: "completed", plan: 1, title: "生成回答" }
      ]
    };

    const result = restoreAgentExecution(json, "NORMAL");

    expect(result.agentExecutionStatus).toBe("completed");
    expect(result.agentSteps?.[1].tool).toEqual(
      expect.objectContaining({
        name: "commerce_search_association_rules",
        label: "购物篮关联规则",
        status: "completed"
      })
    );
    expect(result.agentSteps?.[1].tool?.name).not.toBe("");
    expect(result.agentExecutionSummary).toEqual(
      expect.objectContaining({ planCount: 1, toolCallCount: 1, evidenceCount: 2, replanCount: 0 })
    );
  });

  it("falls back to label as name and default label when tool has neither name nor toolKey", () => {
    const json = {
      steps: [
        {
          seq: 1,
          phase: "tool",
          status: "completed",
          plan: 1,
          title: "工具调用",
          tool: { toolKey: "some_tool" }
        },
        { seq: 2, phase: "tool", status: "completed", plan: 1, title: "未知工具", tool: {} }
      ]
    };

    const result = restoreAgentExecution(json);

    expect(result.agentSteps?.[0].tool).toEqual(
      expect.objectContaining({ name: "some_tool", label: "业务数据查询" })
    );
    expect(result.agentSteps?.[1].tool).toEqual(
      expect.objectContaining({ name: "", label: "业务数据查询" })
    );
  });

  it("derives cancelled status from INTERRUPTED and finalizes running steps", () => {
    const json = {
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" },
        {
          seq: 2,
          phase: "tool",
          status: "running",
          plan: 1,
          title: "业务数据查询",
          tool: { label: "购物篮关联规则", toolKey: "commerce_search_association_rules" }
        },
        { seq: 3, phase: "generation", status: "running", plan: 1, title: "生成回答" }
      ]
    };

    const result = restoreAgentExecution(json, "INTERRUPTED");

    expect(result.agentExecutionStatus).toBe("cancelled");
    expect(result.agentSteps?.[1].status).toBe("cancelled");
    expect(result.agentSteps?.[2].status).toBe("cancelled");
  });

  it("derives failed status from ERROR and finalizes running steps", () => {
    const json = {
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" },
        { seq: 2, phase: "generation", status: "running", plan: 1, title: "生成回答" }
      ]
    };

    const result = restoreAgentExecution(json, "ERROR");

    expect(result.agentExecutionStatus).toBe("failed");
    expect(result.agentSteps?.[1].status).toBe("failed");
  });

  it("keeps completed steps untouched when deriving failed from REJECTED", () => {
    const json = {
      steps: [{ seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" }]
    };

    const result = restoreAgentExecution(json, "REJECTED");

    expect(result.agentExecutionStatus).toBe("failed");
    expect(result.agentSteps?.[0].status).toBe("completed");
  });

  it("sorts steps by seq and falls back to a computed summary when absent", () => {
    const json = {
      steps: [
        { seq: 3, phase: "generation", status: "completed", plan: 2, title: "生成回答" },
        { seq: 2, phase: "tool", status: "completed", plan: 1, title: "业务数据查询", tool: { label: "购物篮关联规则", toolKey: "commerce_search_association_rules", evidenceCount: 3 } },
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" }
      ]
    };

    const result = restoreAgentExecution(json);

    expect(result.agentSteps?.map((step) => step.seq)).toEqual([1, 2, 3]);
    expect(result.agentExecutionSummary).toEqual(
      expect.objectContaining({ planCount: 2, toolCallCount: 1, evidenceCount: 3, replanCount: 0 })
    );
  });

  it("returns empty object for missing/invalid json", () => {
    expect(restoreAgentExecution(undefined)).toEqual({});
    expect(restoreAgentExecution(null)).toEqual({});
    expect(restoreAgentExecution("not-an-object")).toEqual({});
    expect(restoreAgentExecution({ steps: [] })).toEqual({});
    expect(restoreAgentExecution({ summary: {} })).toEqual({});
  });

  it("restores terminalState from summary into agentTerminalState (new data only)", () => {
    const json = {
      summary: { planCount: 1, toolCallCount: 0, evidenceCount: 0, replanCount: 0, terminalState: "refused" },
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" },
        { seq: 2, phase: "generation", status: "completed", plan: 1, title: "生成回答" }
      ]
    };

    const result = restoreAgentExecution(json, "NORMAL");

    expect(result.agentExecutionStatus).toBe("completed");
    expect(result.agentExecutionSummary?.terminalState).toBe("refused");
    expect(result.agentTerminalState).toBe("refused");
  });

  it("omits agentTerminalState when summary has no terminalState (old data)", () => {
    const json = {
      summary: { planCount: 1, toolCallCount: 0, evidenceCount: 0, replanCount: 0 },
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" }
      ]
    };

    const result = restoreAgentExecution(json, "NORMAL");

    expect("agentTerminalState" in result).toBe(false);
    expect(result.agentTerminalState).toBeUndefined();
    // agentExecutionMode 无持久化来源：一律不恢复
    expect("agentExecutionMode" in result).toBe(false);
  });

  it("ignores invalid terminalState value from summary", () => {
    const json = {
      summary: { planCount: 1, toolCallCount: 0, evidenceCount: 0, replanCount: 0, terminalState: "mystery" },
      steps: [
        { seq: 1, phase: "planning", status: "completed", plan: 1, title: "制定计划" }
      ]
    };

    const result = restoreAgentExecution(json, "NORMAL");

    expect(result.agentTerminalState).toBeUndefined();
    expect(result.agentExecutionSummary?.terminalState).toBeUndefined();
  });
});

describe("cancelAgentSteps", () => {
  it("marks running steps as cancelled and leaves others untouched", () => {
    const steps = [
      { stepId: "a", seq: 1, phase: "planning" as const, status: "completed" as const, plan: 1, title: "a" },
      { stepId: "b", seq: 2, phase: "tool" as const, status: "running" as const, plan: 1, title: "b" }
    ];
    const result = cancelAgentSteps(steps);
    expect(result?.[0].status).toBe("completed");
    expect(result?.[1].status).toBe("cancelled");
  });
});

describe("computeAgentExecutionSummary", () => {
  it("counts tool calls and evidence, ignoring non-final tool steps", () => {
    const steps = [
      { stepId: "a", seq: 1, phase: "planning" as const, status: "completed" as const, plan: 1, title: "a" },
      { stepId: "b", seq: 2, phase: "tool" as const, status: "completed" as const, plan: 1, title: "b", tool: { name: "t", label: "工具", status: "completed" as const, evidenceCount: 2 } },
      { stepId: "c", seq: 3, phase: "tool" as const, status: "running" as const, plan: 1, title: "c", tool: { name: "t", label: "工具", status: "running" as const } },
      { stepId: "d", seq: 4, phase: "replan" as const, status: "completed" as const, plan: 2, title: "d" }
    ];
    expect(computeAgentExecutionSummary(steps)).toEqual({
      planCount: 2,
      toolCallCount: 1,
      evidenceCount: 2,
      replanCount: 1
    });
    expect(computeAgentExecutionSummary(undefined)).toBeNull();
    expect(computeAgentExecutionSummary([])).toBeNull();
  });
});
