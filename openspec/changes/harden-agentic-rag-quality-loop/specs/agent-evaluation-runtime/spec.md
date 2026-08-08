## Purpose

Turn versioned evaluation cases into real agent executions and trustworthy release gates whose scores can be reproduced and audited.

## ADDED Requirements

### Requirement: Real runtime execution
Each evaluation case SHALL execute through the same planner, registered tools, evidence review, and answer path used by the application; its reference answer SHALL be scoring input only and SHALL never be copied into the generated answer.

#### Scenario: Evaluation run starts
- **WHEN** an operator evaluates a published knowledge release
- **THEN** every result stores the runtime answer, selected tools, evidence identifiers, terminal state, latency, runtime mode, and configuration snapshot

### Requirement: Multi-dimensional deterministic scoring
The scorer SHALL independently calculate expected-point coverage, expected-evidence retrieval, citation correctness, groundedness, refusal/escalation correctness, and latency, then aggregate them using a versioned scoring configuration.

#### Scenario: Fluent unsupported answer
- **WHEN** an answer is readable but cites no expected evidence or adds unsupported claims
- **THEN** citation and groundedness dimensions fail even if keyword coverage passes

### Requirement: Risk-aware release gates
Release approval SHALL be blocked by failed mandatory safety/refusal cases or configured aggregate thresholds, and the decision SHALL persist the exact gate snapshot.

#### Scenario: Safety case answers without escalation
- **WHEN** a mandatory safety case requires refusal or human escalation but the runtime gives a definitive answer
- **THEN** the run records a high-risk failure and approval is rejected

### Requirement: Honest offline and model-backed reporting
Reports SHALL distinguish deterministic fallback runs from model-backed runs and SHALL NOT combine them into one unlabeled quality claim.

#### Scenario: Offline verification run
- **WHEN** canonical verification runs without LLM, embedding, or vector services
- **THEN** evaluation completes reproducibly and is labeled fallback rather than model quality
