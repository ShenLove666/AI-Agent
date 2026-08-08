## Context

See `proposal.md` for motivation. The current LangGraph coordinator has three hard-coded tool branches and routes evidence retry directly back to tool execution. `SupportService.run_evaluation` persists the reference answer as the runtime answer and assigns fixture scores, so the existing gate cannot measure agent behavior. The implementation must preserve the local-first modular monolith, current API clients, owner isolation, and offline foundation tests.

## Goals / Non-Goals

**Goals:**

- Make planner decisions, tool arguments/results, evidence review, and termination typed and inspectable.
- Run evaluation against the real bounded agent path and persist enough evidence to reproduce every score and gate.
- Preserve deterministic offline verification while keeping its claims separate from model-backed results.

**Non-Goals:**

- Write-capable commerce tools, autonomous customer actions, unbounded multi-agent dialogue, or a framework migration.
- A new frontend dashboard beyond additive trace/metric fields needed by existing views.

## Decisions

### 1. Introduce one in-process typed registry behind the existing coordinator

Create Pydantic input models and a common tool-result envelope for granular `knowledge.*`, `commerce.*`, and `support.*` read operations. A registry resolves names, validates arguments, applies an owner-scoped execution context, and converts expected failures to structured error results. Existing coarse tool names remain temporary aliases so chat contracts do not break.

Alternative: adopt LangChain tools or a remote tool protocol immediately. Rejected because the project already has a small LangGraph runtime and the extra abstraction would not improve the P0 behavior or offline reliability.

### 2. Re-plan through the planner node with explicit history

Extend graph state with plan history, review feedback, observations, tool errors, plan count, and runtime mode. The evidence reviewer routes `retry` to the planner. The planner receives a compact view of prior attempts and must change a query/tool/arguments or terminate. A graph-wide step limit and a tool-call budget prevent loops. The deterministic planner uses the same state to widen from domain data to knowledge or support evidence in a fixed order.

Alternative: retry the tool node with another query index. Rejected because it is retrieval retry, not agent re-planning.

### 3. Separate execution, scoring, and gates

Add an evaluation runner that loads immutable cases, invokes the coordinator per case, generates an answer only from runtime evidence, records monotonic latency, and persists a trace snapshot. Pure scoring functions compute expected-point coverage, expected-document/tool retrieval, citation correctness, groundedness, refusal/escalation correctness, and latency. A versioned gate policy aggregates results and blocks mandatory-risk failures.

The reference answer and expected fields are never passed to the answer generator. Offline answer construction quotes or summarizes returned evidence deterministically and refuses/escalates when evidence review does not reach ready state.

Alternative: LLM-as-judge as the primary score. Rejected because it makes offline verification non-reproducible; it can be added later as a separately labeled optional dimension.

### 4. Keep persistence additive and ownership-scoped

Prefer existing evaluation JSON columns for trace and scoring details. If current columns cannot represent the required runtime mode, tool metrics, and gate snapshot without ambiguity, add Alembic `0007_agent_evaluation_runtime` with nullable/additive columns and full downgrade. Evaluation datasets, releases, runs, and results must share `owner_id` through validated relationships; a release cannot be evaluated against a foreign dataset or exposed across owners.

### 5. Preserve API compatibility

Existing run and overview fields remain. Additive result detail includes `runtimeMode`, `terminalState`, `tools`, `metrics`, `trace`, and evidence identifiers. Execution failure marks a result/run failed with a stable code rather than returning a successful fixture score. The evaluation endpoint may become async internally, while its route and response shape remain compatible.

## Ownership and Security Boundaries

- Tool execution receives owner identity from authenticated application context, never from model-generated arguments.
- Record-id tools query by both id and owner; foreign and missing records are indistinguishable to callers.
- Traces store normalized safe arguments and error codes, not provider keys, raw exceptions, or hidden prompts.
- All tools in this change are read-only; future mutation tools require separate approval and human confirmation.

## Risks / Trade-offs

- [Offline fallback can look stronger than it is] → persist `runtime_mode` and separate fallback/model-backed aggregates.
- [Keyword groundedness is imperfect] → use deterministic conservative checks and retain evidence/trace for audit; optional judge scoring remains separate.
- [Evaluation becomes slower] → bound concurrency and case count per run, store per-case latency, and keep cancellation/failure state explicit.
- [Legacy plans use coarse names] → retain aliases during migration and remove only after contract tests show no active client dependency.

## Migration Plan

1. Add typed contracts/registry and compatibility aliases behind the existing coordinator.
2. Route retry to planner and add history/budget/terminal-state tests.
3. Add real runner, pure scoring, gate policy, and any required `0007` additive migration.
4. Update support evaluation API details and demo evaluation cases without changing seed/reset external dependencies.
5. Run focused backend tests, migration downgrade/upgrade, API contract baseline, canonical verification, and strict OpenSpec validation.

Rollback: restore the previous coordinator and evaluation service, downgrade `0007` if created, and retain existing datasets/releases. New JSON details are additive and can be ignored by old clients.

## Verification

- Tool registry: `.\.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py -q`.
- Re-planning: `.\.venv\Scripts\python.exe -m pytest tests/test_agentic_rag.py -q`.
- Evaluation and gate: `.\.venv\Scripts\python.exe -m pytest tests/test_agent_evaluation_runtime.py tests/test_support_quality.py -q`.
- Migration: `.\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q`.
- Contracts: `.\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py tests/test_api_contract_baseline.py -q`.
- Acceptance: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` and `openspec validate harden-agentic-rag-quality-loop --strict`.
