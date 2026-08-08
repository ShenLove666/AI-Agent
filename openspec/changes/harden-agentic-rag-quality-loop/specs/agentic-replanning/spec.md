## Purpose

Ensure that insufficient or conflicting evidence causes a new bounded planning decision rather than silently repeating the same retrieval attempt.

## ADDED Requirements

### Requirement: Evidence-driven re-planning
When evidence is insufficient, conflicting, or a tool fails, the runtime SHALL return to the planner with reviewer feedback, prior plans, observations, and tool errors before selecting the next action.

#### Scenario: First plan finds no evidence
- **WHEN** the first tool plan returns no usable evidence
- **THEN** the planner is invoked again and the next plan changes query, arguments, or tool strategy, or explicitly refuses or escalates

### Requirement: Bounded safe termination
The runtime SHALL enforce configurable plan and tool-call limits and SHALL terminate with direct answer, grounded answer, refusal, or human escalation.

#### Scenario: Re-planning remains unproductive
- **WHEN** the configured limit is reached without sufficient evidence
- **THEN** the runtime stops calling tools, records the terminal reason, and does not present an unsupported definitive answer

### Requirement: Deterministic offline planning
The runtime SHALL provide a deterministic offline planner that follows the same typed tool and re-planning contracts while being clearly identified as fallback execution.

#### Scenario: No model provider is configured
- **WHEN** an offline test or demonstration asks a business question
- **THEN** the fallback selects relevant registered tools, can revise an unproductive plan, and labels the trace as deterministic fallback

