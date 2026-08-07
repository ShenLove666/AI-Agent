## 1. Repository safety and schema lifecycle

- [x] 1.1 Extend `.gitignore` for generated frontend, Python, test, database, upload, and local-secret outputs; initialize and inspect a local Git baseline without staging ignored or external files.
- [x] 1.2 Add failing migration tests for empty SQLite upgrade, recognized pre-Alembic adoption with preserved rows, and rejection of an unknown partial schema.
- [x] 1.3 Add Alembic configuration and a reviewed baseline revision that represents the complete pre-change schema and supports SQLite batch operations.
- [x] 1.4 Extract the existing compatibility mutations into a quarantined legacy adopter, implement the programmatic migration entry point, and switch application startup to `upgrade head`.
- [x] 1.5 Verify empty upgrade, legacy adoption, downgrade behavior, and the existing backend suite before committing the schema-lifecycle work.

## 2. Demo ownership and document provenance

- [x] 2.1 Add failing persistence and default-value tests for `User.is_demo` and knowledge-document provenance fields.
- [x] 2.2 Add the mapped fields and constrained content-origin vocabulary while preserving ordinary/user-upload defaults for existing rows.
- [x] 2.3 Add the post-baseline migration with explicit upgrade/downgrade operations and verify both clean and legacy upgrade paths.

## 3. Evaluation dataset foundation

- [x] 3.1 Add failing tests for tenant ownership, structured expectation round-tripping, per-dataset stable-key uniqueness, and transactional rollback on an invalid case.
- [x] 3.2 Implement focused `EvaluationDataset` and `EvaluationCase` models plus a repository method that creates a dataset and its initial cases in one transaction.
- [x] 3.3 Register the models, add the ordered migration with upgrade/downgrade operations, and run focused plus full backend tests.

## 4. Validated bundled demo catalog

- [x] 4.1 Add failing catalog tests for stable keys, required public-source provenance, synthetic-content labelling, minimum case count, and valid document references.
- [x] 4.2 Implement the typed manifest loader and fail-fast validation without network access.
- [x] 4.3 Add concise original summaries of the two approved official sources and one explicitly fictional merchant policy, each with the required metadata.
- [x] 4.4 Add at least twelve deterministic merchant-support evaluation cases spanning answer, evidence, scope, and refusal behavior; make all catalog tests pass.

## 5. Idempotent demo seed and safe reset

- [x] 5.1 Add failing service tests proving repeat seed reuses stable entities and reset preserves every ordinary user-owned record in a mixed database.
- [x] 5.2 Implement deterministic demo upsert, knowledge ingestion, evaluation persistence, browseable historical demo records, and dependency-ordered cleanup in a domain service.
- [x] 5.3 Add `seed-demo` and confirmation-protected `clear-demo` CLI adapters without committing passwords or requiring an LLM, Redis, Milvus, or network access.
- [x] 5.4 Exercise both commands against a temporary SQLite database and run focused plus full backend tests.

## 6. Active frontend API contract

- [x] 6.1 Add failing tests for supported service-call extraction, prefix/parameter normalization, explicit streaming-chat coverage, and unmatched-operation reporting.
- [x] 6.2 Implement the checker with a reviewed allowlist of enabled frontend service files; keep hidden future modules explicitly out of scope.
- [x] 6.3 Run the checker against generated FastAPI OpenAPI and resolve every enabled method/path mismatch without adding placeholder endpoints.

## 7. Canonical verification and documentation

- [x] 7.1 Add `scripts/verify.ps1` to run backend compilation/tests, the active API contract check, frontend lint, and the production build with fail-fast exit behavior.
- [x] 7.2 Update the README with prerequisites, migration, demo seed/reset, local startup, test, verification, demo-account, data-provenance, and truthful capability-boundary guidance.
- [x] 7.3 Update project OpenSpec context and documentation links so the approved design, implementation plan, and change artifacts are discoverable.
- [x] 7.4 Run the canonical verification command, repeat clean-database migration and seed smoke tests, and audit that no external project, secret, generated artifact, or out-of-scope capability was added.
