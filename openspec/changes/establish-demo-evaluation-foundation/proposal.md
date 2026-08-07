## Why

The project has a strong RAG chat foundation but cannot yet produce a reproducible, evidence-backed merchant AI product demo: schema upgrades still depend on runtime table mutation, there is no safely isolated demo dataset, evaluation cases have no durable model, and active frontend APIs lack an automated OpenAPI contract gate. Establishing these foundations now prevents later knowledge-operations, diagnosis, evaluation, and dashboard work from being built on disposable data or fragile databases.

## What Changes

- Introduce Alembic as the forward schema lifecycle, including empty-database creation and safe adoption of the existing SQLite schema.
- Mark demo ownership at the user boundary and store provenance for public-summary and synthetic knowledge documents.
- Add a validated, bundled merchant-support demo catalog with official-source summaries and deterministic evaluation cases.
- Add idempotent CLI seed/reset workflows that never delete non-demo user data.
- Add minimal evaluation dataset and evaluation case persistence; evaluation execution and scoring remain outside this change.
- Add an automated contract check between active frontend service calls and FastAPI OpenAPI routes.
- Add one canonical verification command covering backend compile/tests, API contracts, frontend lint, and production build.

## Capabilities

### New Capabilities

- `schema-lifecycle`: Versioned database upgrades for empty and pre-Alembic SQLite databases.
- `demo-data-foundation`: Reproducible, identifiable, safely resettable merchant-support demo data with source provenance.
- `evaluation-dataset-foundation`: Durable evaluation datasets and structured cases without evaluation-run execution.
- `active-api-contract`: Automated verification that every enabled frontend service method/path exists in FastAPI OpenAPI.

### Modified Capabilities

None. The repository has no existing OpenSpec capability specifications.

## Impact

- Adds Alembic to Python API dependencies and introduces migration configuration/revisions.
- Changes application startup from ad-hoc schema creation to versioned upgrades while retaining one-time legacy adoption.
- Extends user and knowledge-document persistence and adds evaluation tables.
- Adds project-owned demo resources, CLI commands, tests, contract tooling, and verification documentation.
- Does not alter `D:\Project\ragent-main`, require external infrastructure, expose unfinished reference-project modules, or implement evaluation runs and dashboards.
