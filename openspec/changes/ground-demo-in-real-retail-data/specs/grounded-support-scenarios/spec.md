## Purpose

Generate a large, varied, deterministic support workload grounded in real retail structures while making synthetic narratives and outcomes impossible to mistake for observed customer-service data.

## ADDED Requirements

### Requirement: Source-linked scenario generation
Each generated support case SHALL reference a source dataset, source basket or invoice key, selected observed line items, generator version, deterministic seed, and a field-lineage map.

#### Scenario: Case detail provenance
- **WHEN** an operator opens a generated case
- **THEN** the case shows its source record, observed products, synthetic fields, generator version, and a clear demo badge

#### Scenario: Reproducible generation
- **WHEN** the same source manifest, scenario version, and seed are used
- **THEN** generated case keys, category distribution, messages, and outcomes are byte-for-byte stable

### Requirement: Realistic scale and coverage
The default demo SHALL contain at least 300 cases across refund, cancellation, promotion, product, delivery, payment, food-safety, invoice, and account categories, with pending, in-progress, resolved, escalated, AI-reviewed, manually handled, and insufficient-evidence outcomes.

#### Scenario: Coverage acceptance
- **WHEN** demo generation completes
- **THEN** every required category and lifecycle outcome meets its declared minimum and the coverage report contains no silent zero-count segment

### Requirement: Scenario constraints follow source limits
Scenario generation SHALL use source-supported product/order facts and SHALL apply explicit constraints so impossible or contradictory cases are rejected before persistence.

#### Scenario: Fresh item no-reason return
- **WHEN** a generated case concerns a fresh or perishable item and requests a no-reason return
- **THEN** the case is classified for policy review and does not automatically promise statutory seven-day no-reason return eligibility

#### Scenario: Cancellation-only source
- **WHEN** an observed cancellation has no recorded reason or delivery event
- **THEN** the scenario does not label a specific cancellation reason or logistics failure as observed

### Requirement: Truthful operational metrics
Reports SHALL allow filtering by observed/derived/synthetic provenance and SHALL prevent generated case outcomes from being presented as production business performance.

#### Scenario: Demo-only report
- **WHEN** all selected cases are generated demo cases
- **THEN** every KPI and export is labeled synthetic-demo and includes generator/source versions

#### Scenario: Mixed report
- **WHEN** demo and ordinary records are selected together
- **THEN** the report separates the populations and does not calculate a single unlabeled blended performance KPI

### Requirement: Human-review usefulness
Generated cases SHALL include enough order/product context, policy evidence, ambiguity, and risk distribution to exercise manual replies, AI review, quality labels, gap creation, knowledge release, evaluation, and gate decisions end to end.

#### Scenario: Interview walkthrough
- **WHEN** a user follows the documented walkthrough from an unresolved case to a release decision
- **THEN** every step operates on persisted source-linked data and the final report traces the case, decision, gap, knowledge version, and evaluation result
