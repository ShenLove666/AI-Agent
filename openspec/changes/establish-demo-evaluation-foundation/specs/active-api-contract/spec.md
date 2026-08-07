## Purpose

Prevent enabled frontend workflows from silently drifting away from FastAPI methods and paths while allowing explicitly hidden future modules to remain out of scope.

## ADDED Requirements

### Requirement: Active service calls match OpenAPI
Every statically discoverable method and path used by an enabled frontend service SHALL match a FastAPI OpenAPI operation after API-prefix and path-parameter normalization.

#### Scenario: Verify the active frontend
- **WHEN** the contract checker scans the configured active service modules and the streaming chat call
- **THEN** it exits successfully only when every discovered method/path pair exists in the generated OpenAPI document

#### Scenario: Detect a missing backend route
- **WHEN** an enabled service adds a method/path pair absent from OpenAPI
- **THEN** the checker exits unsuccessfully and reports the unmatched method and normalized path

### Requirement: Scope exclusions are explicit
Frontend service modules for hidden, future capabilities MUST be excluded through a reviewed active-service list rather than ignored by a wildcard or swallowed error.

#### Scenario: Review contract scope
- **WHEN** an engineer inspects the checker configuration
- **THEN** the exact enabled service filenames and the explicit streaming-chat call are visible

### Requirement: Contract verification is part of canonical validation
The project verification command SHALL run the active API contract check between backend tests and frontend lint/build checks.

#### Scenario: Run full local verification
- **WHEN** an engineer invokes the canonical verification script
- **THEN** any contract mismatch causes a non-zero result and prevents the verification run from reporting success
