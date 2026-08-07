## Why

The current application demonstrates RAG, evaluation, and retail analytics, but it does not give a merchant team a concrete daily workflow or measurable operational outcome. Reframe it as a local-first AI customer-support quality and knowledge-operations workspace so a frontline agent, support lead, and AI operator can move from an incoming case to a reviewed answer, a recorded outcome, and a verified knowledge improvement.

## What Changes

- Add a merchant support inbox with explicit case status, priority, assignee, labels, customer messages, and resolution state.
- Turn AI chat into a human-in-the-loop reply copilot that produces grounded suggestions with citations and supports accept, edit, reject, and escalate decisions.
- Add governed knowledge lifecycle states and immutable published versions; production replies may retrieve only published knowledge.
- Connect real support outcomes and failure labels to a quality queue, versioned regression datasets/runs, release gates, and an evidence-based operations dashboard.
- Replace synthetic vanity metrics on the primary workspace with metrics derived from recorded support events; keep basket analysis as a clearly labeled secondary insight module.
- Seed realistic retail support policies, cases, outcomes, and evaluation inputs so the complete workflow is demonstrable without external services.

## Capabilities

### New Capabilities

- `support-case-management`: Merchant support inbox, case ownership, lifecycle, labels, messages, and resolution records.
- `human-reviewed-ai-replies`: Grounded reply suggestions, citations, risk/fallback behavior, and auditable agent decisions.
- `knowledge-release-control`: Draft, publish, and immutable version behavior for support knowledge used by retrieval.
- `support-quality-loop`: Outcome labeling, knowledge-gap triage, versioned regression evaluation, release gates, and operational metrics.

### Modified Capabilities

- None. The existing instant-retail operations capability remains a secondary, explicitly labeled analytics surface and is not expanded by this change.

## Impact

- Backend: new support, reply-review, knowledge-release, and quality modules; SQLAlchemy models and Alembic migrations; seeded demo scenarios; API contracts and tests.
- Frontend: a task-oriented support inbox, case workspace, knowledge release view, quality queue, evaluation comparison, and evidence-based dashboard.
- Retrieval: published-version filtering and persisted citation/configuration snapshots for each generated suggestion.
- Local-first constraints: SQLite, deterministic demo seed/reset, and the canonical verification suite must work without a configured LLM API, Milvus, or downloaded embedding model; unavailable AI services must fail visibly and preserve manual workflows.
- Deployment evolution: PostgreSQL plus pgvector and S3-compatible storage remain production adapters, not MVP runtime requirements.
- External systems: no live marketplace, social, payment, or messaging integration is required; cases enter through demo seed and local APIs in this change.

## Non-goals

- A general-purpose agent or visual workflow builder, MCP marketplace, graph execution engine, or autonomous tool-running bot.
- Omnichannel integrations, multi-tenant billing, Kubernetes, ClickHouse, Kafka, or a full Langfuse-compatible observability platform.
- Automatic sending of high-risk refund, compensation, legal, or account-security answers without human review.
- Claiming conversion lift from the basket dataset or making basket analytics the primary product workflow.
- Replacing the current React/FastAPI modular-monolith architecture or copying code and restricted visual designs from researched projects.
