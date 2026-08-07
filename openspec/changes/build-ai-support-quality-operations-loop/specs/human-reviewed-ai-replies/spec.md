## Purpose

Turn retrieval-augmented generation into a supervised reply copilot whose evidence, configuration, risks, and final human decision are visible and reproducible for quality review.

## ADDED Requirements

### Requirement: Reply suggestions are grounded and reproducible
The system SHALL persist each AI suggestion with its case, generated text, cited knowledge excerpts, model identifier, prompt version, knowledge version, latency, and generation status.

#### Scenario: Grounded suggestion succeeds
- **WHEN** an agent requests a suggestion and published knowledge supports the answer
- **THEN** the system shows the suggestion with navigable citations and stores the complete generation snapshot

#### Scenario: No adequate evidence is found
- **WHEN** retrieval produces no evidence above the configured acceptance rule
- **THEN** the system returns an explicit insufficient-evidence result and does not present an uncited answer as authoritative

### Requirement: A human controls every customer-facing reply
The system SHALL require an authorized agent to accept, edit, reject, or escalate a suggestion before any reply is recorded as customer-facing, and SHALL persist the decision and final text.

#### Scenario: Agent edits a suggestion
- **WHEN** an agent changes the suggested text and confirms the reply
- **THEN** the system stores both the immutable suggestion and the edited final reply with an `edited` decision

#### Scenario: Agent escalates a risky answer
- **WHEN** an agent selects escalation instead of sending the suggestion
- **THEN** the system changes the case to escalated and records the reason without creating a sent reply

### Requirement: High-risk topics require visible safeguards
The system SHALL flag configured refund, compensation, account-security, legal, and other high-risk topics and SHALL prohibit automatic sending in the MVP.

#### Scenario: Refund compensation is suggested
- **WHEN** a generated suggestion contains a high-risk compensation action
- **THEN** the UI identifies the risk and requires explicit human confirmation or escalation

### Requirement: Provider failures do not corrupt case state
The system SHALL expose generation failures with retry guidance and SHALL NOT append a sent message, change case resolution, or discard an agent draft because of a model, embedding, or retrieval failure.

#### Scenario: Streaming generation is interrupted
- **WHEN** the provider stream fails before completion
- **THEN** the system marks the generation attempt failed and preserves the case and manual draft for retry

