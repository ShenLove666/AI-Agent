## Purpose

Provide safe, inspectable business tools that an agent can select dynamically without bypassing validation, tenant ownership, or evidence provenance.

## ADDED Requirements

### Requirement: Typed tool contracts
Every registered tool SHALL declare a stable name, purpose, validated input schema, and unified result schema containing evidence, provenance, status, and a safe error when execution fails.

#### Scenario: Invalid tool arguments
- **WHEN** a plan supplies missing, malformed, or out-of-range tool arguments
- **THEN** the call is rejected before business data access and the trace records a validation error without a stack trace or secret

### Requirement: Granular read-only business tools
The registry SHALL expose separate read-only operations for knowledge search/document detail, commerce association/product metrics, and support case/quality/gap lookup instead of one broad count-only operation per domain.

#### Scenario: Cross-domain retail question
- **WHEN** a question needs both policy evidence and product behavior
- **THEN** the agent can invoke multiple named tools and preserve the origin of every returned evidence item

### Requirement: Ownership isolation and observability
Every business-data tool SHALL enforce the caller owner scope and SHALL emit duration, normalized arguments, outcome, evidence count, and error code in the agent trace.

#### Scenario: Foreign record requested
- **WHEN** a tool argument identifies a record owned by another merchant
- **THEN** the result reveals no foreign content and records a not-found or forbidden outcome

