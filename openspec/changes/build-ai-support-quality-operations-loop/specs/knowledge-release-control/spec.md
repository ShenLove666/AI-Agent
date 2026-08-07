## Purpose

Ensure support answers use reviewed merchant policy rather than mutable drafts by providing explicit knowledge lifecycle states, immutable publication snapshots, and safe rollback behavior.

## ADDED Requirements

### Requirement: Knowledge has draft and published lifecycle states
The system SHALL allow authorized operators to edit draft knowledge and publish a versioned immutable snapshot, while ordinary agents SHALL only retrieve published versions for customer-facing suggestions.

#### Scenario: Operator publishes a draft
- **WHEN** an authorized operator publishes a valid draft
- **THEN** the system creates a new immutable version and makes it the active retrieval version

#### Scenario: Agent asks before a draft is published
- **WHEN** relevant information exists only in a draft
- **THEN** the reply copilot does not cite or treat that draft as approved policy

### Requirement: Publication is traceable and reversible
The system SHALL record publisher, publication time, source documents, content identity, and processing status for each version and SHALL allow an authorized operator to reactivate a prior valid version without deleting history.

#### Scenario: Operator rolls back bad policy
- **WHEN** an operator reactivates a previous valid knowledge version
- **THEN** future suggestions use that version while prior suggestions continue to reference their original version

### Requirement: Invalid knowledge cannot become active
The system SHALL prevent publication when required source processing failed, content is missing, or the resulting searchable version is incomplete.

#### Scenario: Indexing fails during publication
- **WHEN** one or more required documents fail processing
- **THEN** publication fails visibly and the previously active version remains active

### Requirement: Knowledge processing works with explicit local fallbacks
The system SHALL show whether retrieval uses the configured embedding/index service or a documented local fallback and SHALL never silently claim vector indexing succeeded when it did not.

#### Scenario: Local embedding model is not installed
- **WHEN** an operator processes knowledge without the configured local model
- **THEN** the system reports the missing prerequisite or selected fallback and leaves processing status truthful

