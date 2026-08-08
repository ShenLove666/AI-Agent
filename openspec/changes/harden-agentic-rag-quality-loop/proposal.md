## Why

The current agentic RAG path can select broad data sources, but tool execution is hard-coded, insufficient evidence retries the same execution node without a new plan, and evaluation copies reference answers into results. That makes the demo look agentic without providing a trustworthy quality loop or defensible interview evidence.

## What Changes

- Add a typed tool registry with granular knowledge, commerce, and support tools, Pydantic-validated inputs, unified evidence/error outputs, ownership boundaries, and traceable tool-call metadata.
- Change the LangGraph flow so insufficient evidence returns to the planner with reviewer feedback, previous plans, observations, and errors; bound retries and end in answer, refusal, or human escalation.
- Execute evaluation cases through the real agent runtime, capture answer/evidence/tool/latency traces, score retrieval, citations, groundedness, task outcome, and refusal behavior, and calculate reproducible aggregate gates.
- Keep deterministic offline fallbacks for tests and local demonstrations while clearly distinguishing fallback runs from model-backed runs.
- Preserve existing chat and support API contracts; new trace and metric fields are additive.

## Capabilities

### New Capabilities

- `typed-agent-tools`: Registry-based agent tools with validated inputs, unified results, authorization, and observable execution traces.
- `agentic-replanning`: Evidence-driven planning and bounded re-planning that changes strategy or safely terminates after insufficient evidence.
- `agent-evaluation-runtime`: Real execution, scoring, aggregation, and gate decisions for versioned evaluation cases.

### Modified Capabilities

None.

## Impact

- Backend: `app/modules/rag`, support evaluation services, schemas, persistence, and focused pytest suites.
- APIs: additive agent trace and evaluation detail fields; existing clients remain compatible.
- Data: additive Alembic migration only if persisted tool/metric fields cannot fit existing result and trace tables.
- Dependencies: continue using the existing LangGraph, Pydantic, SQLAlchemy, model router, retriever, and Milvus adapters; no new framework is required.
- External systems: optional configured LLM, embedding, reranking, and Milvus services may improve production runs, but migration, demo seed/reset, and core tests remain offline.

## Non-goals

- Autonomous refunds, order mutation, customer sending, payment execution, or unreviewed high-risk actions.
- Unbounded multi-agent conversation, MCP/UCP integration, framework replacement, or a microservice rewrite.
- Using reference answers as generated answers, treating deterministic fallback metrics as model quality, or claiming synthetic demo cases are production outcomes.
- Large frontend redesign, model fine-tuning, or deleting compatibility APIs in this change.
