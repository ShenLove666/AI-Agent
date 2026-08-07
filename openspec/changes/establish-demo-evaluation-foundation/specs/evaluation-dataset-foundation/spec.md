## Purpose

Provide durable, structured merchant-support evaluation datasets and cases that later evaluation engines can execute and compare reproducibly.

## ADDED Requirements

### Requirement: Evaluation datasets are tenant-owned
Each evaluation dataset SHALL belong to one user and SHALL be distinguishable as demo or ordinary data.

#### Scenario: Create a merchant evaluation dataset
- **WHEN** an authorized owner creates a named dataset
- **THEN** the dataset records its owner, description, demo marker, and creation/update times

### Requirement: Evaluation cases contain testable expectations
Each evaluation case MUST store a stable key, question, category, difficulty, knowledge scope, expected answer points, expected document keys, refusal expectation, and optional reference answer.

#### Scenario: Persist a structured case
- **WHEN** a case with valid expectations is added to a dataset
- **THEN** all list-valued expectations round-trip without loss and remain associated with that dataset

#### Scenario: Reject duplicate stable keys
- **WHEN** two cases in one dataset use the same stable case key
- **THEN** dataset creation fails atomically and neither duplicate case is persisted

### Requirement: Dataset creation is atomic
Creating a dataset and its initial cases SHALL succeed or fail as one database transaction.

#### Scenario: One case is invalid
- **WHEN** any initial case has an empty question, empty expected points, or another validation failure
- **THEN** neither the dataset nor any of its cases is committed

### Requirement: Evaluation execution remains separate
Persisting datasets and cases SHALL NOT imply that an evaluation run, judge score, or dashboard result exists.

#### Scenario: Browse a newly seeded dataset
- **WHEN** a dataset has cases but no future execution records
- **THEN** it is represented as evaluation input only and no fabricated score or run status is returned
