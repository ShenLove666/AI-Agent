## Purpose

Provide a reproducible merchant-support demonstration dataset whose synthetic ownership and public-source provenance are explicit and safely removable.

## ADDED Requirements

### Requirement: Demo data is identifiable
The system SHALL distinguish demo-owned records from ordinary user data through a durable ownership marker.

#### Scenario: Browse seeded demo content
- **WHEN** demo users and their owned records are loaded
- **THEN** downstream APIs and interfaces can determine that the records belong to demo data without relying on display names

### Requirement: Public knowledge keeps provenance
Every bundled public-summary document MUST record its source URL, publisher, retrieval date, content origin, and usage note.

#### Scenario: Inspect a public summary
- **WHEN** an operator inspects a seeded public-summary document
- **THEN** the document exposes official-source provenance and states that the bundled text is an original summary for demonstration

#### Scenario: Validate an invalid public source
- **WHEN** a public-summary catalog item omits its URL, publisher, retrieval date, or usage note
- **THEN** catalog loading fails before database records are created

### Requirement: Seed is deterministic and idempotent
The system SHALL create the same stable demo entities from the same bundled catalog and SHALL reuse them on repeated seed operations.

#### Scenario: Seed twice
- **WHEN** an operator runs the seed command twice without resetting
- **THEN** the second run reports reused entities and does not duplicate users, knowledge bases, documents, or evaluation cases

### Requirement: Reset preserves ordinary data
The system MUST delete only demo-owned database and external resources during reset.

#### Scenario: Clear demo data in a mixed database
- **WHEN** demo and ordinary users both own records and an operator confirms demo reset
- **THEN** all demo-owned records and collected demo external resources are removed while every ordinary user record remains

### Requirement: Demo seed works without external AI infrastructure
The seed and reset workflow SHALL NOT require an LLM API, Redis, Milvus, or another network service.

#### Scenario: Seed in local lightweight mode
- **WHEN** the project uses SQLite, local files, keyword retrieval, and no configured model key
- **THEN** demo users, knowledge, structured evaluation cases, and browseable historical demonstration records are created successfully
