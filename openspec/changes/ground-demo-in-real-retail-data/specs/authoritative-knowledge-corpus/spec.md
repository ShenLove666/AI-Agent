## Purpose

Provide a useful merchant-support knowledge corpus whose summaries are original, versioned, source-attributed, freshness-aware, and constrained by explicit applicability and legal-review boundaries.

## ADDED Requirements

### Requirement: Authoritative source metadata
Every formal knowledge document SHALL include publisher, canonical source URL, source title, jurisdiction, effective or publication date when available, retrieval date, content checksum, applicability, exclusions, usage note, and provenance type.

#### Scenario: Official return-rule summary
- **WHEN** the corpus includes an online-return summary
- **THEN** it links to the current State Administration for Market Regulation source and states that fresh/perishable goods can fall outside seven-day no-reason return rules

#### Scenario: Missing mandatory attribution
- **WHEN** a formal document lacks publisher, canonical URL, retrieval date, or applicability
- **THEN** release validation blocks publication and identifies the missing metadata

### Requirement: Original summaries rather than source mirrors
The system SHALL store project-authored summaries, decision tables, examples, and escalation rules and SHALL NOT require or present a full copied third-party legal or platform-policy text as project-owned content.

#### Scenario: User opens a citation
- **WHEN** a user inspects evidence for a suggested reply
- **THEN** the interface shows the project summary, exact source metadata, retrieval date, applicability note, and a link to the canonical source

### Requirement: Freshness and supersession
The system SHALL calculate source freshness from declared review intervals, distinguish current, review-due, and superseded documents, and exclude superseded or blocked documents from new active releases.

#### Scenario: Source review is overdue
- **WHEN** the next-review date has passed
- **THEN** operators see a review-due warning and publication requires an explicit reviewed-at update or documented override

#### Scenario: Version rollback
- **WHEN** operators roll back to a previously published knowledge release
- **THEN** the active corpus and retrieval scope atomically return to that immutable snapshot while later history remains visible

### Requirement: Operational policy separation
The system SHALL distinguish authoritative external guidance from merchant-authored operating policies and SHALL make conflicts or stricter merchant commitments visible.

#### Scenario: Merchant promise is more favorable
- **WHEN** a merchant-authored return promise exceeds the statutory baseline
- **THEN** replies cite both the authoritative baseline and the merchant commitment and apply the more favorable valid commitment

#### Scenario: Safety-sensitive uncertainty
- **WHEN** food-safety evidence is incomplete or conflicting
- **THEN** the system recommends stopping consumption and human escalation rather than presenting a definitive medical or legal conclusion
