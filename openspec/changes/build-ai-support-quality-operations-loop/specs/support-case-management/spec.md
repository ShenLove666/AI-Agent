## Purpose

Provide a concrete merchant-support work queue in which every customer issue has an owner, lifecycle, conversation history, and auditable resolution instead of being an isolated chatbot session.

## ADDED Requirements

### Requirement: Authorized staff can manage a support inbox
The system SHALL list merchant-owned cases with status, priority, assignee, labels, customer summary, last activity, and unread state, and SHALL support filtering by those fields.

#### Scenario: Agent opens the pending queue
- **WHEN** an authorized agent filters the inbox to pending high-priority cases
- **THEN** the system returns only matching merchant-owned cases ordered by actionable recency

#### Scenario: User requests another merchant's case
- **WHEN** a user requests a case outside their ownership boundary
- **THEN** the system returns a not-found or forbidden response without disclosing case data

### Requirement: Cases follow a controlled lifecycle
The system SHALL support `pending`, `in_progress`, `resolved`, and `escalated` states, SHALL record the actor and timestamp for each transition, and SHALL require a resolution code before a case becomes resolved.

#### Scenario: Agent starts and resolves a case
- **WHEN** an assigned agent moves a pending case to in-progress and then supplies a resolution code
- **THEN** the system persists both transitions and exposes the resolved outcome in the case timeline

#### Scenario: Resolution code is missing
- **WHEN** an agent attempts to resolve a case without a resolution code
- **THEN** the system rejects the transition and leaves the previous state unchanged

### Requirement: Conversation history is append-only
The system SHALL append customer, agent, system, and AI-suggestion events to a case timeline and SHALL NOT silently overwrite previously sent customer or agent messages.

#### Scenario: Agent sends an edited reply
- **WHEN** an agent confirms a reply to a case
- **THEN** the final reply is appended with its actor and timestamp while the prior customer messages remain unchanged

### Requirement: Manual handling remains available offline
The system SHALL allow staff to view, assign, label, escalate, and resolve cases when model or retrieval services are unavailable.

#### Scenario: AI provider is unavailable
- **WHEN** the AI provider cannot be reached
- **THEN** the case remains actionable and the agent can write and save a manual reply

