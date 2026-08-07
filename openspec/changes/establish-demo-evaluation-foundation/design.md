## Context

See `proposal.md` for motivation. The application currently registers SQLAlchemy models in a FastAPI container and mutates older SQLite schemas at startup through `create_all` plus a hand-maintained `ALTER TABLE` map. Demo data, source provenance, and evaluation inputs have no durable boundaries. The frontend contains both enabled services and hidden reference-project services, so the contract gate must distinguish actual product scope from retained future code.

The implementation must remain local-first: SQLite and local files are sufficient, `D:\Project\ragent-main` is read-only, and no model API or external vector service is required for this foundation.

## Goals / Non-Goals

**Goals:**

- Establish one versioned database lifecycle for empty and recognized legacy databases.
- Make demo ownership and source provenance machine-readable.
- Seed/reset a fixed merchant-support catalog safely and repeatedly.
- Persist structured evaluation inputs with transactional integrity.
- Fail verification when an enabled frontend service drifts from OpenAPI.

**Non-Goals:**

- Execute evaluation cases, call an LLM judge, or compute dashboard scores.
- Add Agent, MCP, graph, intent, or distributed ingestion features.
- Make hidden frontend services pass by adding placeholder APIs.
- Require PostgreSQL, Redis, Milvus, or network access at seed time.

## Decisions

### 1. Use an explicit Alembic baseline plus one-time legacy adoption

The baseline revision represents the complete pre-change schema. Empty databases run all revisions normally. A database with the recognized pre-Alembic application schema first runs the quarantined legacy-column adoption routine, is stamped at the baseline, and then upgrades forward.

This is chosen over continuing runtime `ALTER TABLE` because revisions become reviewable and testable. It is chosen over treating existing databases as disposable because the user already has local conversations and knowledge data. Unknown partial schemas fail closed rather than being guessed into shape.

### 2. Put the demo boundary on the owning user

`User.is_demo` is the authoritative reset boundary. Knowledge, conversations, traces, and evaluation data inherit demo status through ownership. Public-source provenance remains on each document because provenance is document-specific.

This avoids adding `is_demo` to every child table while still allowing safe dependency-ordered deletion. Reset first resolves the complete set of demo-owned database and external resource identifiers, then deletes only that set.

### 3. Bundle original summaries, not remote snapshots

The repository includes concise original summaries of two official sources and one explicitly fictional store policy. A typed catalog records URL, publisher, retrieval date, usage note, content origin, and a stable key. Seed time never downloads remote content.

This makes demos deterministic and offline while preserving evidence and avoiding full-page copyright copying. The official source is identified as authoritative in every summary.

### 4. Keep evaluation inputs independent of evaluation execution

The change adds tenant-owned datasets and cases only. A case contains stable structured expectations and knowledge scope, but no run status or score. Dataset-and-case creation is one transaction.

This boundary lets later deterministic and LLM-judge runners evolve without rewriting seed data or inventing scores before execution exists.

### 5. Use an explicit active-service contract scope

The checker statically extracts supported `api.get/post/put/patch/delete` calls from a reviewed list of enabled service files and adds the fetch-based streaming call explicitly. It normalizes API prefixes and parameter names before comparing with generated FastAPI OpenAPI.

This is preferred to forcing hidden reference services to pass through 501 endpoints, because hidden capabilities are not part of the product. It is preferred to scanning all TypeScript files because dynamic UI helpers and retained future modules would obscure the actual enabled contract.

### 6. Seed through a domain service, with CLI as an adapter

Catalog validation, idempotent upsert, ingestion, evaluation persistence, historical demo records, and reset live in a service callable from tests. CLI commands only parse confirmation/password inputs and print typed result counts.

This prevents business logic from becoming untestable command-line code and leaves a clean path for a later admin endpoint without duplicating seed behavior.

## Risks / Trade-offs

- **Legacy schemas may differ from the known project history** → Compare table/column signatures before stamping; fail with recovery guidance for unknown shapes.
- **Circular conversation/message foreign keys complicate generated baseline order** → Review the generated revision explicitly and test empty upgrade plus full downgrade in SQLite batch mode.
- **User-level demo ownership requires careful dependent deletion** → Resolve IDs first, delete in dependency order, and test a mixed demo/ordinary database.
- **Static TypeScript extraction cannot understand arbitrary computed URLs** → Restrict enabled service URLs to literals/template literals and require an explicit declared call for exceptional fetch flows.
- **Official pages can change after bundling** → Store retrieval date and source URL; summaries remain clearly dated and state that the source page prevails.
- **SQLite downgrade behavior can rebuild tables** → Use Alembic batch operations and treat production-like rollback as a tested maintenance operation, not an automatic startup action.

## Migration Plan

1. Add and verify the baseline revision against an empty temporary SQLite database.
2. Move existing runtime compatibility mutations into a one-time legacy adopter.
3. Test adoption using a pre-Alembic database fixture containing existing rows.
4. Add the demo/provenance revision and confirm existing rows default to ordinary/user-upload semantics.
5. Add the evaluation revision and verify upgrade/downgrade ordering.
6. Change FastAPI lifespan startup to programmatic `upgrade head`.
7. Keep `Database.create_schema()` temporarily as a deprecated wrapper for tests, then migrate callers during this change.

Rollback is manual: stop the application, back up the SQLite file, run Alembic downgrade to the selected revision, and restore the backup if downgrade validation fails. Demo reset is separate from schema rollback and never runs automatically.
