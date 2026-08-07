## Purpose

Provide a local-first, evidence-backed instant-retail merchant workflow that converts authorized shopping-basket data into explainable campaigns, Agent quality improvements, operational insights, and interview-ready reports without misrepresenting synthetic enrichment as real business data.

## ADDED Requirements

### Requirement: Authorized basket data import
The system SHALL import `GoodsOrder.csv` and `GoodsTypes.csv` from a user-supplied local directory, validate their required columns, repair the known source encoding, reject unusable input atomically, and preserve source-row identity and provenance.

#### Scenario: Valid source directory is imported
- **WHEN** an administrator imports files containing `id,Goods` order rows and `Goods,Types` mappings
- **THEN** the system stores tenant-owned baskets, items, products, categories, import counts, a source fingerprint, and `data_origin=source`

#### Scenario: Import is repeated
- **WHEN** the same tenant imports files with the same content fingerprint again
- **THEN** the system returns the existing import result without duplicating baskets, items, or products

#### Scenario: Source data is invalid
- **WHEN** a required file, column, decodable product name, or usable basket row is missing
- **THEN** the system rejects the import, persists no partial commerce graph, and returns a safe validation summary without exposing unrelated filesystem content

### Requirement: Honest deterministic demo enrichment
The system SHALL generate missing price, time, store, channel, fulfillment, after-sales, campaign-exposure, and AI-usage fields deterministically from a declared seed and SHALL label every generated field or record as synthetic.

#### Scenario: Same seed is reused
- **WHEN** demo enrichment runs twice for the same imported dataset and seed
- **THEN** the generated values and aggregate metrics are identical and no duplicate records exist

#### Scenario: Provenance is displayed or exported
- **WHEN** a user views a metric, evidence record, or report containing generated values
- **THEN** the system identifies the values as simulated and distinguishes them from source shopping-basket facts

### Requirement: Explainable basket insights
The system SHALL calculate order count, product count, average basket size, category coverage, and association-rule support, confidence, and lift from stored basket evidence.

#### Scenario: User opens basket insights
- **WHEN** a merchant with imported data opens the insights view
- **THEN** the system returns computed summary metrics, filterable association rules, calculation definitions, provenance, and evidence basket identifiers

#### Scenario: Evidence threshold is not met
- **WHEN** a candidate rule has fewer than the configured minimum co-occurrences or fails the configured support threshold
- **THEN** the system excludes it from actionable recommendations and explains the threshold

#### Scenario: Tenant attempts cross-merchant access
- **WHEN** a user requests another merchant's rule or evidence basket
- **THEN** the system denies access without revealing whether that evidence exists

### Requirement: Merchant onboarding readiness
The system SHALL provide a merchant profile and a readiness checklist for data import, knowledge readiness, evaluation dataset readiness, model configuration, and launch threshold status.

#### Scenario: Readiness contains a blocker
- **WHEN** any required launch condition is incomplete
- **THEN** the checklist identifies the blocking condition and the next action instead of marking the merchant ready

#### Scenario: Optional model is unavailable
- **WHEN** no live LLM credential is configured
- **THEN** deterministic analytics and seeded evaluation results remain browsable while live generation is explicitly marked unavailable

### Requirement: Evidence-backed campaign workflow
The system SHALL let an authorized merchant create, edit, version, approve, and retire a bundle campaign from a qualifying association rule while preserving the rule snapshot and human approval.

#### Scenario: Campaign draft is created
- **WHEN** an operator selects a qualifying rule
- **THEN** the draft records target product, paired product, source rule metrics, applicable channel, copy, status, and source-data provenance

#### Scenario: Campaign is published
- **WHEN** an authorized operator approves a draft
- **THEN** the system creates an immutable campaign version and a versioned knowledge artifact that can be retrieved by the AI assistant

#### Scenario: Model proposes unsupported metrics
- **WHEN** generated campaign copy contains a numerical claim not present in the rule or approved campaign inputs
- **THEN** the system rejects or removes the unsupported claim before the draft can be approved

### Requirement: Evaluation execution and human labeling
The system SHALL execute deterministic evaluation cases, optionally request live answers when an LLM is configured, store configuration snapshots and result evidence, and allow authorized human labels.

#### Scenario: Evaluation run completes
- **WHEN** an operator runs a dataset against a campaign and knowledge version
- **THEN** each result stores expected-point coverage, citation correctness, refusal correctness, latency where available, answer evidence, and the model, prompt, knowledge, and campaign version snapshot

#### Scenario: Human reviews a failure
- **WHEN** an operator labels a result
- **THEN** the label records pass/fail, failure category, severity, note, reviewer, and timestamp without overwriting the machine result

#### Scenario: Live model is unavailable
- **WHEN** a live run requires an unavailable model provider
- **THEN** the run fails with an actionable configuration error while existing results and deterministic checks remain available

### Requirement: Evidence-backed operations dashboard
The system SHALL aggregate onboarding, assistant usage, knowledge hit, resolution, escalation, feedback, satisfaction, and evaluation-pass metrics from persisted source or synthetic events and SHALL expose evidence drill-downs.

#### Scenario: Metric has evidence
- **WHEN** a user opens an operational metric
- **THEN** the system returns numerator, denominator, time range, provenance mix, and identifiers for authorized supporting records

#### Scenario: Metric has no valid denominator
- **WHEN** a rate cannot be computed because its denominator is zero
- **THEN** the system returns an explicit insufficient-data state rather than a fabricated zero percent

### Requirement: Optimization task and re-evaluation loop
The system SHALL create tenant-owned optimization tasks from failed evaluations, negative feedback, knowledge misses, or escalations and SHALL enforce the lifecycle `new → confirmed → optimizing → pending_verification → resolved`.

#### Scenario: Invalid transition is requested
- **WHEN** an operator attempts to skip a required optimization state
- **THEN** the system rejects the transition and leaves the task unchanged

#### Scenario: Task is resolved
- **WHEN** a pending-verification task has a linked change version and a qualifying re-evaluation result
- **THEN** an authorized operator can resolve it with before/after evidence retained

### Requirement: Auditable weekly operations report
The system SHALL generate an operations report from persisted metrics, insights, tasks, and evaluation comparisons with an explicit data-source statement.

#### Scenario: Report is generated
- **WHEN** an operator selects a supported reporting period
- **THEN** the report contains metric definitions, provenance, key insights, evidence-linked issues, completed actions, evaluation change, and next steps

#### Scenario: Unsupported growth claim is requested
- **WHEN** report content cannot be supported by stored evidence
- **THEN** the system omits the claim and states that evidence is insufficient

### Requirement: Local demo and safe cleanup
The system SHALL provide one command that creates or reuses the complete instant-retail demo and one command that clears only owned demo records and managed files.

#### Scenario: Demo is created offline
- **WHEN** the seed command runs with SQLite and no optional external service
- **THEN** the merchant profile, source-derived fixture, synthetic enrichment, campaigns, knowledge, seeded evaluation results, optimization tasks, and dashboard evidence are available

#### Scenario: Demo is cleared
- **WHEN** clear runs after seed
- **THEN** only demo-owned records and managed project files are removed, ordinary users and their records remain intact, and cleanup failure remains safely retryable
