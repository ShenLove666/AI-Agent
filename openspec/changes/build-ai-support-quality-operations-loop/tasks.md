## 1. Support Data Foundation

- [x] 1.1 Add support-case, message, event, suggestion, decision, knowledge-release, quality-label, gap, evaluation-run/result, and release-decision models plus an additive Alembic migration with downgrade coverage. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q`; expected: all selected migration upgrade/downgrade tests pass.
- [x] 1.2 Extend deterministic demo seed/reset with realistic retail policies, 30-50 support cases, reviewed outcomes, gaps, and evaluation inputs while preserving fail-closed ownership cleanup. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_demo_seed.py -q`; expected: seed, idempotency, reset, ownership, and file-safety tests pass.

## 2. Support Inbox and Case Lifecycle

- [x] 2.1 Implement ownership-scoped inbox/detail queries with status, priority, assignee, label, unread, and search filters plus append-only timelines. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_cases.py -q -k "inbox or detail or timeline or ownership"`; expected: selected query and isolation tests pass.
- [x] 2.2 Implement assignment, label, lifecycle, resolution-code, escalation, conflict, and manual-reply mutations with atomic event recording. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_cases.py -q -k "transition or assign or label or resolve or manual or conflict"`; expected: selected mutation and rollback tests pass.
- [x] 2.3 Expose typed FastAPI support routes and lock their authorization/error contracts. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py -q -k "case or inbox"`; expected: selected API contract tests pass.
- [x] 2.4 Build the frontend support inbox and queue/detail workspace with real filtering, assignment, transitions, manual replies, responsive behavior, and loading/empty/error states. Verify with `npm --prefix web test -- SupportInbox.test.tsx CaseWorkspace.test.tsx`; expected: both focused UI suites pass.

## 3. Human-Reviewed Reply Copilot

- [x] 3.1 Implement suggestion generation snapshots, published-knowledge retrieval scope, typed insufficient-evidence/provider-failure results, citations, and risk flags. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_reply_review.py -q -k "suggestion or citation or unavailable or risk"`; expected: selected grounding and failure-path tests pass.
- [x] 3.2 Implement accept, edit, reject, and escalate decisions without mutating suggestion evidence or appending unintended sent messages. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_reply_review.py -q -k "accept or edit or reject or escalate or immutable"`; expected: selected decision, audit, and transaction tests pass.
- [x] 3.3 Add suggestion/review APIs and a case evidence panel with citations, safeguards, manual fallback, preserved drafts, and actionable retry states. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py -q -k "suggestion or decision"` and `npm --prefix web test -- ReplyCopilot.test.tsx`; expected: backend contracts and focused UI suite pass.

## 4. Governed Knowledge Releases

- [x] 4.1 Implement draft, publish, activate/rollback, immutable membership snapshots, validation, and truthful processing state while filtering formal retrieval to the active published version. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_knowledge_release.py -q`; expected: publication, rollback, filtering, concurrency, and failure tests pass.
- [x] 4.2 Add knowledge release APIs and the operator UI for draft status, publication readiness, active/history comparison, rollback, and missing-model/index feedback. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py -q -k "knowledge or release"` and `npm --prefix web test -- KnowledgeReleases.test.tsx`; expected: backend contracts and focused UI suite pass.

## 5. Quality, Evaluation, and Evidence-Based Operations

- [x] 5.1 Implement quality labels and deduplicated knowledge-gap queue operations with frequency, severity, evidence links, ownership, and resolution version. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_quality.py -q -k "label or gap"`; expected: selected labeling, aggregation, isolation, and resolution tests pass.
- [x] 5.2 Implement immutable evaluation runs/results, deterministic rule scores, run comparison, blocking high-risk gates, and atomic release decisions. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_quality.py -q -k "evaluation or comparison or gate or release"`; expected: selected execution, immutability, regression, and gate tests pass.
- [x] 5.3 Implement event-derived operations metrics and provenance-aware reports with truthful empty/demo states. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_quality.py -q -k "metric or report or provenance"`; expected: selected aggregation and no-fabrication tests pass.
- [x] 5.4 Build quality queue, evaluation comparison/gate, and operations report pages; move basket analysis under clearly labeled secondary insights without breaking its route. Verify with `npm --prefix web test -- QualityQueue.test.tsx EvaluationRuns.test.tsx SupportOperations.test.tsx`; expected: all focused UI suites and legacy-route coverage pass.

## 6. Product Integration and Acceptance

- [x] 6.1 Replace primary product navigation and workspace copy with Workbench, Cases, Knowledge, Quality, Evaluation, and Reports; preserve authentication guards, accessibility, responsive overlays, and bookmarked legacy routes. Verify with `npm --prefix web test` and `npm --prefix web run lint`; expected: all frontend tests and lint pass.
- [x] 6.2 Complete API-route contract coverage, document local model download/fallback behavior, and add a reproducible manual walkthrough from pending case through reviewed reply, gap resolution, candidate evaluation, and gate decision. Verify with `\.venv\Scripts\python.exe -m pytest tests/test_support_api_contracts.py -q` and `\.venv\Scripts\python.exe -m pytest tests/test_demo_seed.py -q`; expected: all support contracts and demo lifecycle tests pass.
- [x] 6.3 Run canonical repository verification and strict OpenSpec validation. Verify with `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` and `openspec validate build-ai-support-quality-operations-loop --strict`; expected: verification exits 0 and the change is valid.
