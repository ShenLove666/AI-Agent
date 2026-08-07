## Purpose

Convert support outcomes into an evidence-based improvement loop that identifies knowledge gaps, compares versioned behavior, enforces release gates, and reports operational value without synthetic claims.

## ADDED Requirements

### Requirement: Staff can label reply quality and failure cause
The system SHALL support `correct`, `partially_correct`, and `incorrect` quality labels and structured failure causes including missing knowledge, retrieval failure, stale policy, generation error, and unsafe answer.

#### Scenario: Supervisor marks missing knowledge
- **WHEN** a supervisor labels a reviewed reply incorrect because policy was absent
- **THEN** the system creates or updates a traceable knowledge-gap item linked to the case and suggestion

### Requirement: Knowledge gaps have an operational queue
The system SHALL list unresolved gaps with frequency, severity, linked cases, owner, status, and target knowledge version, and SHALL preserve the source evidence after resolution.

#### Scenario: Operator resolves a repeated gap
- **WHEN** an operator links a published knowledge version and marks a gap resolved
- **THEN** the gap retains its linked cases and records the resolving version and actor

### Requirement: Evaluation runs are immutable and comparable
The system SHALL execute versioned evaluation cases against a fixed model, prompt, and knowledge configuration; each run SHALL preserve inputs, outputs, citations, scores, errors, and configuration snapshot.

#### Scenario: Operator compares candidate and active versions
- **WHEN** two completed runs use the same dataset with different knowledge versions
- **THEN** the system displays comparable overall, category, citation, and high-risk results without rewriting either run

### Requirement: Release gates protect high-risk behavior
The system SHALL block promotion when configured minimum correctness or citation thresholds fail, when any blocking high-risk case regresses, or when the run is incomplete.

#### Scenario: Candidate improves average but breaks a refund case
- **WHEN** a candidate run improves aggregate score but fails a blocking refund case
- **THEN** the system marks the gate failed and does not promote the candidate

### Requirement: Dashboard metrics derive from recorded events
The system SHALL calculate case volume, resolution rate, suggestion acceptance rate, edit rate, escalation rate, citation coverage, top failure causes, and unresolved-gap counts from persisted workflow records and SHALL disclose empty or demo-only provenance.

#### Scenario: No production events exist
- **WHEN** the selected time range contains no qualifying events
- **THEN** the dashboard shows an empty state rather than fabricated positive metrics

#### Scenario: Demo data is displayed
- **WHEN** metrics include seeded demo records
- **THEN** the dashboard visibly identifies the demo provenance and does not present it as production performance
