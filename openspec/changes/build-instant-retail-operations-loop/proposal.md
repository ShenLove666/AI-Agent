## Why

The project already demonstrates RAG engineering, but it lacks a concrete merchant workflow that proves product landing, Agent quality operations, and data-driven optimization. An instant-retail supermarket scenario turns the existing chat, knowledge, evaluation, and demo foundations into a coherent portfolio case backed by 9,835 real shopping baskets.

## What Changes

- Add a local, idempotent importer for the authorized shopping-basket source files with explicit source/synthetic provenance.
- Add deterministic commerce demo enrichment for prices, stores, channels, fulfillment, after-sales, campaign exposure, and AI usage events.
- Add explainable basket metrics and association rules with order-level evidence.
- Add merchant onboarding readiness, bundle-campaign creation/versioning, and publication to the existing knowledge workflow.
- Add evaluation results, human labels, optimization tasks, evidence-backed operational metrics, and weekly reports.
- Replace the visible digital-electronics positioning with an instant-retail supermarket operations workspace only where real APIs exist.
- Add migrations, permissions, API contracts, frontend tests, demo commands, documentation, and an eight-minute interview walkthrough.

## Capabilities

### New Capabilities

- `instant-retail-operations`: Source-data import, deterministic demo enrichment, basket insights, merchant readiness, campaign workflow, evaluation labeling, operational evidence, optimization tasks, and report output.

### Modified Capabilities

None.

## Impact

- Backend: new bounded modules for commerce, operations, and optimization; extensions to demo, evaluation, knowledge, CLI, and Alembic migrations.
- Frontend: new operational routes, API services, navigation, evidence drill-downs, provenance labels, and empty/error states.
- Data: SQLite remains the default; imported source rows and generated rows are distinguishable and tenant-owned.
- External systems: no Redis, Milvus, hosted database, or optional LLM API is required for migration, seed, browsing seeded results, or baseline tests.
- Source distribution: the repository does not package the full external dataset because no explicit redistribution license was found; local import accepts a user-provided directory and the repository includes only documented, derived fixtures required by tests.

## Non-goals

- General-purpose Agent orchestration, MCP management, knowledge graphs, or intent-tree editors.
- Production attribution of synthetic revenue, conversion, fulfillment, or customer metrics.
- Automated campaign publication to a real ecommerce platform.
- Multi-node job execution, cloud deployment, or a second vector database requirement.
- Competitor research and trend briefs; these remain a separately approved second phase.
