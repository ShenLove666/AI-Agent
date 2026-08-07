## Context

See `proposal.md` for motivation. The existing commerce import correctly reads the 9,835-basket GBK corpus, but it currently writes generated order times, channels, store keys, and unit prices while marking baskets/items as `source`. The support seed also creates only 36 cases and the formal release contains three documents, one of which is fictional. The change must repair those truthfulness defects without requiring network or AI at runtime.

The local corpus contains only basket id and product name plus a 169-product category mapping. UCI Online Retail II supplies real invoice time, quantity, unit price, customer id, country, and explicit cancellation identifiers for a UK non-store gift retailer under CC BY 4.0; it does not supply cancellation reasons, logistics, or support conversations. Chinese operational knowledge will therefore use project-authored summaries with canonical official links, including SAMR online-return rules and consumer-rights implementation rules, NPC e-commerce law, and official food-safety materials.

## Goals / Non-Goals

**Goals:**

- Make false provenance structurally difficult: no generated value can be serialized as observed/source.
- Retain the full local basket corpus and add a compact, deterministic UCI subset with cancellation coverage and license attribution.
- Generate at least 300 useful support cases while exposing exactly which fields are observed, derived, or synthetic.
- Grow the active knowledge release to at least 10 useful, source-attributed documents plus explicit merchant operating procedures.
- Keep seed/reset, tests, and the default keyword-retrieval path fully offline.

**Non-Goals:**

- Translating the UK dataset into a claim about Chinese market performance.
- Importing PII, reproducing full legal texts, or sending generated replies to real customers.
- Adding a live warehouse, marketplace connector, vector dependency, or model training pipeline.

## Decisions

### 1. Extend the existing commerce schema instead of creating a parallel order system

Alembic `0006_retail_data_provenance` will add:

- `data_sources`: `id`, `owner_id`, `dataset_key`, `version`, `title`, `source_kind`, `source_uri`, `publisher`, `license`, `retrieved_at`, `encoding`, `schema_json`, `limitations_json`, `transform_version`, `manifest_sha256`, `is_demo`, timestamps; unique `(owner_id, dataset_key, version)`.
- `commerce_imports`: nullable `data_source_id`, `accepted_row_count`, `rejected_row_count`, `quality_report_json`.
- `commerce_products`, `commerce_baskets`, and `commerce_basket_items`: replace ambiguous values with a constrained `provenance` (`observed|derived|synthetic`), add `lineage_json`; baskets also gain nullable `customer_key`, `country`, `invoice_status`; items retain nullable observed quantity/price.
- `support_cases`: nullable `source_data_id`, `source_record_key`, `generator_version`, `generator_seed`, `field_lineage_json`.
- `knowledge_documents`: `source_title`, `source_jurisdiction`, `source_effective_at`, `next_review_at`, `review_status`, `applicability_json`, `exclusions_json`, `license_or_usage_note`.

Migration backfill will mark currently generated `ordered_at`, `store_key`, `channel`, and `unit_price` values as synthetic in lineage rather than preserving the incorrect `source` claim. Downgrade removes additive columns/tables but cannot restore the old truthfulness label; it maps all provenance back to the legacy `data_origin` vocabulary.

Alternative considered: new order tables. Rejected because the workbench and basket analysis already depend on commerce ids, and a parallel model would duplicate ownership and deletion logic.

### 2. Use immutable normalized snapshots and manifests

The user directory remains read-only. A project script will read its GB18030/GBK files, validate exact counts, normalize them to UTF-8 gzip assets, and write a manifest containing original checksums and transformation metadata under the repository-managed demo asset directory.

The UCI acquisition step downloads the official workbook into a project-local ignored cache, verifies a pinned checksum, and produces a deterministic stratified snapshot containing normal invoices and cancellations across months/countries. The normalized snapshot, attribution, DOI, license, selection rules, and counts are committed; runtime never downloads it.

Alternative considered: commit the 43.5 MB workbook. Rejected due repository size and unnecessary Excel parsing at runtime.

### 3. Use explicit field lineage, not only a row-level badge

Every generated case has a compact JSON map such as:

```json
{
  "products": {"provenance":"observed","source":"local-baskets-v1","record":"basket:42"},
  "orderedAt": {"provenance":"synthetic","generator":"support-scenarios-v2"},
  "issueReason": {"provenance":"synthetic","template":"fresh-damage-v2"}
}
```

APIs return both a summary provenance and this map on detail endpoints. Metrics group or separate populations by provenance. Unknown is represented by a null value plus limitation, never by a plausible generated default.

Alternative considered: a boolean `is_synthetic`. Rejected because one record can mix observed products with synthetic narrative/outcome fields.

### 4. Generate constrained scenarios from source facts

The generator selects real baskets/invoices with a pinned seed, then applies versioned templates subject to category and source constraints. It creates 300-500 cases across nine support categories and lifecycle/decision variants. It never derives a reason from a UCI cancellation or a delivery failure from a basket with no delivery data. Fresh-food return templates incorporate the authoritative exception and force review; safety templates force stop-consumption/escalation language.

Generation runs entirely in memory before one database transaction. Coverage validation, stable case-key collision checks, and ownership checks complete before any mutation. Reset follows the existing demo ownership closure and source manifest ids.

### 5. Build an attributed knowledge pack of summaries and merchant procedures

The repository stores original Markdown summaries, not mirrored source pages. Each document has a sidecar manifest entry with canonical URL, publisher, retrieval/effective dates, applicability/exclusions, checksum, review interval, and usage note. Initial pack:

1. SAMR network purchase seven-day no-reason return rules.
2. Consumer Rights Protection Law implementation regulation.
3. NPC E-commerce Law obligations and dispute handling.
4. Official food-safety escalation baseline.
5. Refund-to-original-payment and coupon handling decision table.
6. Fresh/perishable damage evidence and escalation SOP.
7. Delivery delay/lost-order merchant SOP.
8. Stock substitution and out-of-stock consent SOP.
9. Promotion stacking and partial-return calculation SOP.
10. Invoice/payment anomaly escalation SOP.
11. Account/security and verification-code safety SOP.
12. Complaint escalation and response-time SOP.

External official summaries and merchant-authored SOPs are separate provenance types. Publication blocks missing attribution, expired review status without override, missing chunks, or conflicting applicability.

### 6. Add provenance and coverage APIs without breaking current clients

Additive endpoints:

- `GET /api/v1/data-sources`
- `GET /api/v1/data-sources/{id}/quality`
- `GET /api/v1/support/cases/{id}/provenance`
- `GET /api/v1/support/coverage`
- `GET /api/v1/support/knowledge/sources`

Existing case, metrics, release, and retail overview payloads gain optional provenance/coverage fields. Legacy clients ignore them. Frontend adds a Data Sources page, provenance drawer on case detail, knowledge source/freshness table, and report filters. The existing basket route remains secondary and shows observed versus generated fields explicitly.

## Ownership and Deletion Boundaries

- Managed source rows require `owner_id`, `is_demo=true`, and a recognized manifest key/version.
- Seed/reset fails closed if a demo source is linked to an ordinary owner or if ordinary records reference managed source rows.
- External user files and the original dataset directory are never deleted, renamed, or modified.
- Managed normalized files are deleted only when their canonical path is within the project-managed demo asset root and no retained import references them.
- Acquisition failure leaves the previously verified normalized snapshot untouched.

## Risks / Trade-offs

- [Real transactions are from an older UK gift retailer, not Chinese instant retail] → Show geography/time/business limitations on every source view and use it only for structure, price/time/cancellation facts.
- [Large fixtures slow seed and tests] → Store compressed normalized assets, batch inserts, use a bounded deterministic UCI subset, and keep a tiny fixture for unit tests.
- [Official pages can move or change] → Store retrieval metadata/checksums, review dates, canonical links, and project-authored summaries; do not silently refresh during runtime.
- [Hundreds of generated cases can still look real] → Persistent field lineage, prominent synthetic-demo badges, provenance filters, and exports that carry source/generator versions.
- [Migration exposes earlier mislabeled data] → Backfill as mixed/synthetic and show an audit note instead of deleting historical rows.

## Migration Plan

1. Add `0006_retail_data_provenance` and backfill legacy provenance truthfully.
2. Add manifest/normalization tools and verified local/UCI snapshots.
3. Add loaders and source-quality APIs; test failure atomicity and ownership isolation.
4. Add the attributed knowledge pack and release validation.
5. Replace demo scenario generation, reset existing managed demo data, and reseed the local database.
6. Add frontend provenance/coverage/source views and update the walkthrough.
7. Run canonical verification and strict OpenSpec validation.

Rollback: stop the service, downgrade one revision, restore the pre-change database backup if old seeded identities are required, and check out the previous managed asset version. Ordinary data is not removed by rollback.

## Verification

- Migration: `.\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q`.
- Source loader/lineage: `.\.venv\Scripts\python.exe -m pytest tests/test_retail_provenance.py -q`.
- Demo ownership/idempotency: `.\.venv\Scripts\python.exe -m pytest tests/test_demo_seed.py -q`.
- Knowledge attribution/release: `.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_sources.py tests/test_knowledge_release.py -q`.
- Scenario coverage/constraints: `.\.venv\Scripts\python.exe -m pytest tests/test_grounded_support_scenarios.py tests/test_support_quality.py -q`.
- API contracts: `.\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py tests/test_api_contract_baseline.py -q`.
- Frontend: `npm --prefix web test -- DataSources.test.tsx CaseProvenance.test.tsx KnowledgeSources.test.tsx SupportOperations.test.tsx` plus lint/build.
- Acceptance: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` and `openspec validate ground-demo-in-real-retail-data --strict`.
