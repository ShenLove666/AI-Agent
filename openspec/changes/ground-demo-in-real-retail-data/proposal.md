## Why

The current demo proves the support workflow but its small synthetic corpus cannot support credible operational analysis or interview claims. The project needs a reproducible, provenance-first dataset that distinguishes real source records from derived and synthetic fields, and a larger authoritative knowledge corpus whose answers can be traced to named official sources.

## What Changes

- Import the user-provided GBK shopping-basket corpus as a project-owned, deterministic snapshot: 9,835 baskets, 43,367 basket lines, 169 products, and 10 categories.
- Add a second optional public real-transaction fixture derived from UCI Online Retail II (CC BY 4.0) for timestamps, quantities, prices, customers, countries, and recorded cancellations; keep its original UK/non-store-retail context visible.
- Introduce row-level and dataset-level provenance (`observed`, `derived`, `synthetic`) with source URI, license, retrieval date, transform version, checksums, and field lineage.
- Expand the merchant demo to hundreds of support cases grounded in observed baskets/orders. Customer language, delivery states, damage reasons, and resolution outcomes remain explicitly synthetic unless present in the source.
- Replace the single fictional knowledge base with a governed corpus of original project summaries linked to authoritative Chinese sources, including online-return rules, consumer-rights implementation rules, e-commerce obligations, food-safety escalation, refund/payment handling, delivery exceptions, promotions, and merchant operating procedures.
- Add data-quality and coverage views that show record counts, date/category coverage, missing fields, source mix, synthetic ratios, knowledge-source freshness, and unsupported scenario warnings.
- Preserve fully offline seed/reset after assets have been acquired; no LLM, embedding model, Milvus, or external API is required to seed or test.
- **BREAKING**: existing demo counts and fixed demo case keys will be replaced by versioned corpus identifiers; APIs remain compatible but seeded record identities and displayed metrics change.

## Capabilities

### New Capabilities

- `retail-data-provenance`: Versioned ingestion, validation, lineage, licensing, checksums, and truthful observed/derived/synthetic field classification for retail fixtures.
- `authoritative-knowledge-corpus`: Source-attributed, freshness-aware, versioned knowledge documents built from authoritative materials without copying full third-party texts.
- `grounded-support-scenarios`: Large deterministic support scenarios linked to source orders/baskets with visible synthetic-field boundaries and coverage metrics.

### Modified Capabilities

None. The existing APIs and support lifecycle remain compatible; this change replaces and expands their demo inputs.

## Impact

- Backend: demo catalog/seed service, new retail fixture loader and provenance models, support scenario generator, knowledge release validation, reporting APIs, and an additive Alembic migration.
- Frontend: data provenance, coverage, knowledge-source, and case-detail indicators; existing workbench and secondary basket route remain available.
- Repository assets: normalized subsets and manifests stored inside the project. The user-provided directory is read-only and is never changed.
- External systems: acquisition commands may read UCI and authoritative government pages, but committed/managed snapshots make runtime and verification offline.
- Dependencies: prefer existing Python standard library/pandas-compatible tooling already available; do not add model or infrastructure dependencies.

## Non-goals

- Claiming that synthetic customer messages, delivery failures, refunds, or resolutions are observed business events.
- Treating the GBK shopping-basket corpus as containing prices, dates, customers, logistics, or after-sales outcomes that it does not contain.
- Mirroring full legal texts or platform-proprietary policies; the corpus stores original summaries, citations, applicability, and retrieval metadata.
- Production PII ingestion, live marketplace integration, real payment/refund execution, autonomous customer sending, model fine-tuning, or replacing legal review.
