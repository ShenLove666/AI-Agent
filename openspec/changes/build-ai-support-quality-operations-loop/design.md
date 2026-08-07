## Context

See `proposal.md` for motivation. The repository already has FastAPI/SQLAlchemy/Alembic services, React/Zustand pages, RAG conversations, document ingestion, evaluation inputs, deterministic demo ownership, and a retail operations page. The new workflow must reuse those foundations without requiring an external model, vector database, or downloaded embedding model to migrate, seed, browse cases, or run the foundation tests.

## Goals / Non-Goals

**Goals:**

- Build one coherent modular-monolith path from support case to reviewed reply, outcome, quality finding, knowledge release, and regression evidence.
- Preserve immutable evidence at business decision boundaries while keeping local startup and reset deterministic.
- Make API contracts and UI states truthful when optional AI infrastructure is absent.

**Non-Goals:**

- Splitting the application into microservices or introducing Redis/Celery solely for this MVP.
- Migrating local development away from SQLite in this change.
- Sending replies to real commerce or messaging platforms.

## Decisions

### 1. Add bounded modules around a shared case timeline

Create backend modules for `support`, `reply_review`, `knowledge_release`, and `quality`, each with schemas, service boundaries, router registration, and ownership checks. A support case is the aggregate root; messages, status transitions, suggestions, decisions, labels, and resolution events refer to it. This keeps transactional operations in one database and avoids premature services. Alternative: reuse generic conversations alone. Rejected because they lack assignment, lifecycle, resolution, and quality semantics.

### 2. Store immutable evidence snapshots, not mutable foreign-key views only

Suggestion and evaluation records store identifiers plus the exact model/prompt/knowledge configuration and citation payload used at execution time. Agent final replies are separate timeline entries and never overwrite suggestions. Knowledge publication creates immutable version records with document-version memberships. Alternative: resolve all display fields from current configuration. Rejected because later edits would make historical decisions unreproducible.

### 3. Keep retrieval behind the existing adapter and add publication filtering

The retrieval service receives an active published knowledge-version scope. SQLite/local fallback remains supported; PostgreSQL+pgvector is a later deployment adapter. Missing model/index configuration returns a typed unavailable or insufficient-evidence result. Alternative: mandate Milvus or pgvector immediately. Rejected because it would break local-first verification and slow the interview demo.

### 4. Use append-only operational events for metrics

Case transitions, suggestion decisions, labels, gap resolution, publication, and evaluation completion append actor/timestamp events in the same transaction as aggregate changes. Dashboard queries aggregate those persisted records and return provenance counts. Alternative: seed precomputed KPI cards. Rejected because such metrics cannot demonstrate real use or survive audit.

### 5. Separate evaluation inputs, execution, and release decisions

Existing dataset/case inputs remain immutable test definitions. A new run snapshots configuration and owns per-case results. Rule scores are deterministic where possible; optional LLM judging is explicitly labeled and never the sole blocking signal. A release gate is evaluated from a completed run and writes a decision record. Alternative: recompute results on page load. Rejected because comparisons would drift and failures would be unauditable.

### 6. Deliver a task-oriented frontend instead of a platform builder

Primary navigation becomes Workbench, Cases, Knowledge, Quality, Evaluation, and Reports. The case workspace uses a queue/detail/evidence layout with explicit loading, empty, unavailable, and error states. The existing basket page remains reachable under secondary insights with provenance text. Alternative: add the new data to the current generic admin dashboard. Rejected because it would preserve the unclear product story.

### 7. Migrate additively and preserve deterministic demo cleanup

Alembic adds support tables and nullable links without reinterpreting ordinary users or documents. Demo seed owns only rows linked to demo users and managed demo files; clear/reset follows existing fail-closed ownership rules. Downgrade drops only new indexes/tables/columns after verifying dependencies. Legacy conversation data is not automatically converted to resolved support cases.

## Data and API Contracts

- New records: support cases, case participants/messages, case events, reply suggestions, reply decisions, knowledge releases/memberships, quality labels, knowledge gaps, evaluation runs/results, and release decisions.
- IDs are opaque; all read/write APIs enforce owner or role scope. Mutations use optimistic version or expected-state checks for case transitions and publication.
- Initial APIs cover inbox list/detail, assignment/transition, manual reply, suggestion generation/review, knowledge draft/publish/rollback, quality labels/gaps, evaluation run/compare/gate, and metric summary.
- Deletes are not exposed for sent messages, suggestions, completed runs, published releases, or audit events. Demo reset removes only proven demo-owned graphs and managed files.

## Acceptance and Verification

- Backend tests: `tests/test_support_cases.py`, `tests/test_reply_review.py`, `tests/test_knowledge_release.py`, `tests/test_support_quality.py`, `tests/test_support_api_contracts.py`, migration upgrade/downgrade coverage, and demo seed/reset coverage.
- Frontend tests: inbox filtering/lifecycle, case workspace review actions, unavailable-provider fallback, knowledge publish failure, quality queue, evaluation comparison/gate, and dashboard empty/demo provenance.
- Contract check: generated/declared frontend API paths and payloads match FastAPI routes.
- Canonical acceptance: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` from the repository root, plus a documented manual demo from seeded pending case through resolved gap and passing candidate release.

## Risks / Trade-offs

- [Broad vertical slice could become another collection of shallow pages] → Implement and verify the case/reply decision path before knowledge and reporting surfaces; no page is accepted without a backed mutation and empty/error state.
- [SQLite concurrency differs from production PostgreSQL] → Use short transactions, expected-state checks, and tests for conflicting transitions; document PostgreSQL as the production target.
- [Generated replies may be unsafe or unsupported] → Require human action, explicit citations, typed insufficient-evidence results, and blocking high-risk cases.
- [Demo events could be mistaken for real outcomes] → Return and display provenance on all metric and report responses.
- [Existing analytics and navigation may conflict] → Preserve routes during migration, move them under secondary insights, and test bookmarked URLs.

## Migration Plan

1. Add and migrate the additive schema; seed realistic support policies, cases, labels, and evaluation inputs under demo ownership.
2. Register read-only inbox/detail APIs, then controlled lifecycle and manual reply mutations.
3. Add suggestion/review evidence, knowledge releases, quality gaps, evaluation runs/gates, and derived metrics in that order.
4. Replace primary navigation only after all new route guards and fallback states pass tests; retain legacy route redirects or links.
5. Rollback frontend routes first, then downgrade the database only when no external consumer depends on new APIs. Downgrade never deletes ordinary user documents or legacy conversations.
