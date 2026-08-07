## Context

See `proposal.md` for motivation and `specs/instant-retail-operations/spec.md` for observable behavior. The repository is a FastAPI/SQLAlchemy/Alembic modular monolith with React/Vite, an existing demo seed service, evaluation inputs, knowledge ingestion, RAG chat, and admin routes. The new flow crosses persistence, analytics, evaluation, knowledge, API, and UI boundaries but must remain runnable with SQLite and without an external model or vector service.

The authorized source contains 43,367 `id,Goods` rows for 9,835 baskets and 169 `Goods,Types` mappings. Product text has a repairable legacy encoding; the source does not contain commercial timestamps, prices, customer identities, stores, or outcomes.

## Goals / Non-Goals

**Goals:**

- Keep source facts immutable and visibly distinct from deterministic synthetic enrichment.
- Deliver the shortest coherent portfolio path: import → insight → campaign → evaluation → optimization → report.
- Make every displayed metric reproducible and evidence-drillable.
- Preserve tenant ownership and safe demo reset behavior.
- Keep module files focused instead of extending the already large demo service.

**Non-Goals:**

- Online experiment assignment or causal-inference claims.
- Live ecommerce campaign publication or real customer PII.
- Full autonomous Agent/tool orchestration.
- Mandatory LLM, Milvus, Redis, or background worker infrastructure.

## Decisions

### 1. Use three bounded modules and explicit service contracts

Create `app/modules/commerce` for merchant profiles, imports, products, baskets, rules, and campaigns; `app/modules/operations` for usage events, readiness, metrics, and reports; and `app/modules/optimization` for issue/task state. Extend `evaluation` with run/result/label models and services. The demo coordinator calls module services and does not write their tables directly.

Alternative: place everything in `demo/service.py` and `api/dashboard.py`. Rejected because it would couple disposable seed mechanics to production-shaped behavior and worsen existing file-size debt.

### 2. Persist normalized evidence and cached rule snapshots

Add tables in one Alembic revision after current head:

- `merchant_profiles(id, owner_id UNIQUE, name, business_type, store_count, goal, stage, is_demo, created_at, updated_at)`
- `commerce_imports(id, owner_id, source_key, fingerprint, status, source_row_count, basket_count, product_count, error_summary, created_at)` with unique `(owner_id, fingerprint)`
- `products(id, owner_id, source_key, name, category, data_origin, is_demo)` with unique `(owner_id, source_key)`
- `baskets(id, owner_id, import_id, source_basket_key, ordered_at, store_key, channel, data_origin, is_demo)` with unique `(import_id, source_basket_key)`
- `basket_items(id, basket_id, product_id, quantity, unit_price, source_row_key, data_origin)` with unique `(basket_id, source_row_key)`
- `association_rules(id, owner_id, import_id, antecedent_product_id, consequent_product_id, cooccurrence_count, support, confidence, lift, min_count, fingerprint, computed_at)`
- `campaigns(id, owner_id, rule_id, name, status, current_version, is_demo, created_at, updated_at)`
- `campaign_versions(id, campaign_id, version, channel, copy, rule_snapshot_json, knowledge_document_id, approved_by, approved_at, created_at)` with unique `(campaign_id, version)`
- `operation_events(id, owner_id, event_key, event_type, occurred_at, conversation_id, message_id, campaign_version_id, payload_json, data_origin, is_demo)` with unique `(owner_id, event_key)`
- `evaluation_runs(id, owner_id, dataset_id, campaign_version_id, status, config_snapshot_json, started_at, completed_at, error_summary, is_demo)`
- `evaluation_results(id, run_id, case_id, answer, expected_point_score, citation_correct, refusal_correct, latency_ms, evidence_json)` with unique `(run_id, case_id)`
- `evaluation_labels(id, result_id UNIQUE, reviewer_id, verdict, failure_category, severity, note, created_at, updated_at)`
- `optimization_tasks(id, owner_id, source_type, source_id, title, status, assignee_id, target_metric, change_version, verification_run_id, before_evidence_json, after_evidence_json, is_demo, created_at, updated_at)`

Foreign keys use restrictive ownership-safe deletion except child records wholly owned by a parent aggregate, which cascade. Demo cleanup selects roots by `owner_id` plus `User.is_demo`; it never deletes by filename glob or shared path.

Alternative: compute every association rule on request. Rejected because repeated pair generation over the full dataset would slow UI reads and make campaign evidence mutable. Rules are recomputed explicitly from an immutable import fingerprint and stored as auditable snapshots.

### 3. Import from an explicit directory, never a repository hard-coded path

Add CLI `commerce import-baskets --source-dir <absolute-or-relative-path> --owner <username>` and `demo seed-retail --source-dir <path> --seed 20260807`. The importer opens only the two exact filenames after canonical containment, regular-file, and identity checks; it reads CSV without spreadsheet formula execution. It first stages and validates all rows in memory, calculates a SHA-256 content fingerprint, then writes one transaction.

Encoding repair accepts correctly decoded Chinese or repairs the known mojibake transformation. A row that remains blank or undecodable is rejected with row number; diagnostics do not echo arbitrary file contents.

Alternative: copy the complete external dataset into the repository. Rejected because redistribution permission is not established.

### 4. Deterministic enrichment is field-level provenance

Use a seeded, stable hash of `(seed, source_basket_key, product_key, field_name)` rather than process-global randomness. Source item membership stays untouched. Generated time, store, channel, unit price, fulfillment, after-sales, exposure, and usage events are reproducible and marked `synthetic`; source basket/product identity remains `source`.

This permits realistic dashboards without claiming those outcomes came from the original dataset.

### 5. Association analysis is deterministic and thresholded

For each basket, deduplicate product presence before pair counting. For directed rule `A → B`:

- `support = count(A∩B) / basket_count`
- `confidence = count(A∩B) / count(A)`
- `lift = confidence / (count(B) / basket_count)`

Default actionability thresholds are `cooccurrence_count >= 60` and `support >= 0.005`; API query parameters may raise but not silently lower the configured floor. Rule evidence returns a bounded page of source basket keys.

### 6. Campaign publication creates a knowledge version through a port

Commerce defines a `CampaignKnowledgePublisher` protocol. The application adapter produces a managed Markdown document containing approved terms and source-rule definitions, ingests it with the existing knowledge service, and records the returned document ID on the immutable campaign version. LLM-generated text is optional; deterministic templates remain available. A numeric-claim validator allows only values present in the rule snapshot or explicit operator inputs.

Alternative: let the chat service query campaign tables directly. Rejected because it bypasses existing scope, citation, ingestion, and trace behavior.

### 7. Evaluation separates machine evidence from human judgment

An evaluation run freezes dataset, model, prompt, knowledge document, and campaign version identifiers. Deterministic scorers operate without an LLM. Live generation is an injected optional answer provider. Human labels are separate rows so reruns and reviewer changes do not alter machine evidence.

Seeded completed runs are explicitly marked demo/synthetic. The UI never presents them as live model results.

### 8. Metrics use typed numerator/denominator/evidence responses

Operational endpoints return `{key, value, numerator, denominator, unit, period, provenance, evidence_refs, data_state}`. Rates with a zero denominator use `value=null` and `data_state="insufficient_data"`. Drill-down endpoints re-check owner scope before resolving evidence references.

Reports render from the same metric and evidence DTOs; they do not ask an LLM to invent analysis. Initial export is Markdown download to avoid adding a document-generation dependency.

### 9. API and frontend routes are additive and lazy

Add authenticated `/api/retail/*` endpoints for readiness, imports, insights, rules/evidence, campaigns/versions, evaluation runs/results/labels, metrics/evidence, optimization tasks/transitions, and reports. Admin users may select an owner; ordinary users are bound to their own owner ID.

Add lazy frontend routes under `/admin/retail`: overview, onboarding, baskets, campaigns, evaluations, optimization, and reports. The navigation replaces digital-electronics copy with instant-retail wording. Pages share provenance badges and loading/empty/error/forbidden states; hidden routes are not exposed before their API is functional.

## Risks / Trade-offs

- [Large row count slows SQLite seed] → use batched inserts inside one transaction, indexed ownership/import keys, cached rule rows, and a focused performance smoke budget.
- [Synthetic enrichment is mistaken for real outcomes] → persist field-level origin, show badges and report disclosures, and test all public DTOs for provenance.
- [Unknown external dataset license] → import locally, commit only small derived test fixtures, and document the user-supplied source requirement.
- [Campaign publishing can leave an external knowledge artifact after DB failure] → record managed ownership before ingestion and compensate on failure using the existing safe cleanup pattern.
- [In-memory vectors disappear after process restart] → application lifespan reindexes managed completed demo documents when the memory backend is selected; persistent backends keep current behavior.
- [Scope is broad] → implement in vertical slices, with the first accepted slice ending at source import, basket insights, and a real overview UI.

## Migration Plan

1. Add the new Alembic revision with empty tables and indexes; do not backfill existing users or conversations.
2. Deploy code that tolerates merchants with no commerce profile and returns explicit empty readiness states.
3. Run the new retail seed against a new or existing demo owner; existing merchant-support demo data remains untouched until the retail seed succeeds.
4. Switch visible branding/navigation after the overview, onboarding, and basket APIs pass contract tests.
5. Rollback UI by hiding additive routes. Database downgrade drops only the new tables/columns in reverse foreign-key order; existing RAG and demo tables remain intact.

## Verification Map

- `tests/test_retail_import.py`: encoding, validation, fingerprint idempotency, transaction rollback, tenant ownership, and 43,367-row source smoke.
- `tests/test_basket_insights.py`: summary metrics, rule formulas, thresholds, evidence pagination, and authorization.
- `tests/test_retail_demo.py`: deterministic enrichment, provenance, seed reuse/reset, external cleanup compensation, and memory-vector restart reindex.
- `tests/test_campaigns.py`: lifecycle, version snapshots, knowledge publication, unsupported numeric claims, and permissions.
- `tests/test_evaluation_runs.py`: offline scoring, configuration snapshots, optional provider failure, labels, and immutable machine evidence.
- `tests/test_operations_loop.py`: metric numerator/denominator, insufficient-data semantics, drill-down, optimization transitions, re-evaluation evidence, and report claims.
- `tests/test_retail_migrations.py`: empty upgrade, existing-head upgrade, downgrade, and foreign-key integrity.
- `scripts/check_api_contract.py`: new frontend services and OpenAPI paths/methods/DTO fields.
- `web/src/pages/admin/retail/RetailFlow.test.tsx`: onboarding blocker, basket rule evidence, campaign creation, labeling, task transitions, provenance, and empty/error states.
- `web/src/components/layout/RetailNavigation.test.tsx`: lazy routes, role guards, keyboard navigation, and no inaccessible hidden overlay content.
- `scripts/verify.ps1`: backend pytest, API contract, frontend Vitest, ESLint, and production build.
