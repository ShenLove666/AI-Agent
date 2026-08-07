## 1. Persistence and migrations

- [ ] 1.1 Add commerce, operations, evaluation-run, and optimization SQLAlchemy models plus an Alembic revision with ownership, uniqueness, foreign-key, and query indexes; verify with `\.venv\Scripts\python.exe -m pytest tests/test_retail_migrations.py -q` and expect empty-head upgrade, existing-head upgrade, downgrade, and FK checks to pass.
- [ ] 1.2 Register the new models and router-independent services with the application/container without changing existing RAG behavior; verify with `\.venv\Scripts\python.exe -m pytest tests/test_application.py tests/test_migrations.py -q` and expect all existing application and migration tests to pass.

## 2. Source import and deterministic demo data

- [ ] 2.1 Implement the safe two-file basket loader with required-column validation, Chinese/mojibake repair, canonical file checks, content fingerprinting, and atomic staging; verify with `\.venv\Scripts\python.exe -m pytest tests/test_retail_import.py -k "loader or invalid or encoding" -q` and expect all selected validation tests to pass.
- [ ] 2.2 Implement tenant-owned, idempotent commerce persistence and the `commerce import-baskets` CLI; verify with `\.venv\Scripts\python.exe -m pytest tests/test_retail_import.py -k "idempotent or rollback or ownership or source_smoke" -q` and expect the 43,367-row smoke plus rollback/ownership tests to pass.
- [ ] 2.3 Implement stable-hash demo enrichment and origin metadata for time, price, store, channel, fulfillment, after-sales, exposure, and usage events; verify with `\.venv\Scripts\python.exe -m pytest tests/test_retail_demo.py -k "deterministic or provenance" -q` and expect repeat runs to produce byte-equivalent facts and source/synthetic assertions to pass.
- [ ] 2.4 Extend demo seed/clear with `seed-retail`, safe ownership closure, retryable compensation, and memory-vector startup reindex for managed completed documents; verify with `\.venv\Scripts\python.exe -m pytest tests/test_retail_demo.py -q` and expect seed→reuse→clear, fault injection, ordinary-user preservation, and restart-reindex tests to pass.

## 3. Basket insight vertical slice

- [ ] 3.1 Implement deterministic basket summaries and directed association-rule calculation with cached import snapshots, configured floors, and bounded evidence identifiers; verify with `\.venv\Scripts\python.exe -m pytest tests/test_basket_insights.py -k "summary or formula or threshold" -q` and expect exact support/confidence/lift examples and threshold tests to pass.
- [ ] 3.2 Add authenticated retail readiness, import summary, insight, rule list, and rule-evidence APIs with owner scoping and typed insufficient-data responses; verify with `\.venv\Scripts\python.exe -m pytest tests/test_basket_insights.py -k "api or authorization or evidence" -q` and expect merchant/admin access matrices, pagination, and zero-denominator cases to pass.
- [ ] 3.3 Add lazy instant-retail overview, onboarding, and basket-insight pages with provenance labels, calculation help, rule filters, evidence drill-down, and loading/empty/error/forbidden states; verify with `npm test -- --run web/src/pages/admin/retail/RetailOverview.test.tsx web/src/pages/admin/retail/BasketInsights.test.tsx` from `web` and expect all selected UI behavior tests to pass.

## 4. Campaign and knowledge workflow

- [ ] 4.1 Implement campaign draft, lifecycle, immutable versions, rule snapshots, numeric-claim validation, and tenant permissions; verify with `\.venv\Scripts\python.exe -m pytest tests/test_campaigns.py -k "lifecycle or version or claim or permission" -q` and expect all selected domain/API tests to pass.
- [ ] 4.2 Implement compensated campaign-to-knowledge publication through the existing knowledge service and managed document ownership; verify with `\.venv\Scripts\python.exe -m pytest tests/test_campaigns.py -k "knowledge or compensation or citation" -q` and expect publication, ingestion failure cleanup, retry, and retrievable-document tests to pass.
- [ ] 4.3 Add campaign list/editor/version UI with evidence context and deterministic copy fallback; verify with `npm test -- --run web/src/pages/admin/retail/CampaignsPage.test.tsx` from `web` and expect create, unsupported-claim, approve, version, and provider-unavailable tests to pass.

## 5. Evaluation and human labeling

- [ ] 5.1 Implement evaluation runs/results, immutable configuration snapshots, deterministic scorers, and optional answer-provider failure semantics; verify with `\.venv\Scripts\python.exe -m pytest tests/test_evaluation_runs.py -k "run or snapshot or scorer or provider" -q` and expect offline and configured-provider scenarios to pass.
- [ ] 5.2 Implement human labels that preserve machine evidence plus evaluation result/label APIs with owner scope; verify with `\.venv\Scripts\python.exe -m pytest tests/test_evaluation_runs.py -k "label or immutable or authorization" -q` and expect reviewer audit and access-control tests to pass.
- [ ] 5.3 Add evaluation run, failure filtering, evidence comparison, and labeling UI; verify with `npm test -- --run web/src/pages/admin/retail/EvaluationsPage.test.tsx` from `web` and expect seeded-results, live-run error, label, and provenance behavior to pass.

## 6. Operations and optimization loop

- [ ] 6.1 Implement readiness and operational metric aggregation with numerator, denominator, provenance mix, evidence references, and insufficient-data semantics; verify with `\.venv\Scripts\python.exe -m pytest tests/test_operations_loop.py -k "readiness or metric or evidence or insufficient" -q` and expect aggregate-to-source reconciliation tests to pass.
- [ ] 6.2 Implement optimization-task creation, lifecycle enforcement, linked change versions, re-evaluation verification, and before/after evidence; verify with `\.venv\Scripts\python.exe -m pytest tests/test_operations_loop.py -k "task or transition or verification" -q` and expect valid transitions, rejected skips, permissions, and resolution gates to pass.
- [ ] 6.3 Implement evidence-backed Markdown weekly reports with data-source disclosure and unsupported-claim suppression; verify with `\.venv\Scripts\python.exe -m pytest tests/test_operations_loop.py -k "report or claim" -q` and expect metric reconciliation, disclosure, download, and insufficient-evidence tests to pass.
- [ ] 6.4 Add operations dashboard, optimization board, and report UI with metric drill-down and before/after comparison; verify with `npm test -- --run web/src/pages/admin/retail/OperationsLoop.test.tsx` from `web` and expect drill-down, state transition, report, and no-data tests to pass.

## 7. Product integration and portfolio delivery

- [ ] 7.1 Replace digital-electronics copy with instant-retail branding, add only functional lazy retail routes/navigation, and preserve auth/keyboard/overlay behavior; verify with `npm test -- --run web/src/components/layout/RetailNavigation.test.tsx web/src/components/auth/AuthBootstrap.test.tsx web/src/components/layout/OverlayAccessibility.test.tsx` from `web` and expect all navigation, guard, focus, and initialization tests to pass.
- [ ] 7.2 Extend the frontend/OpenAPI contract checker for every retail service and DTO; verify with `\.venv\Scripts\python.exe scripts/check_api_contract.py` and expect exit code 0 with no missing method, path, or required field.
- [ ] 7.3 Update README, sample environment, shortest startup/seed commands, data provenance, demo accounts, eight-minute interview walkthrough, and outcome/non-goal language; verify with `\.venv\Scripts\python.exe -m pytest tests/test_documentation_contract.py -q` and expect every documented command/route/credential source and disclosure assertion to pass.
- [ ] 7.4 Run the complete canonical verification from the repository root using `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`; expect backend tests, API contracts, frontend Vitest, ESLint, and Vite production build to complete with exit code 0.
- [ ] 7.5 Run a fresh SQLite acceptance smoke using the documented retail seed, start, API walkthrough, and clear commands; expect the eight-minute flow to show source/synthetic provenance, rule evidence, campaign publication, seeded evaluation, optimization verification, report download, and zero remaining demo users after clear.
