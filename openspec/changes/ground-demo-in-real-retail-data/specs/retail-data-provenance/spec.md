## Purpose

Provide a reproducible and inspectable retail-data foundation that makes every source, transformation, license, limitation, and synthetic field visible to users and downstream features.

## ADDED Requirements

### Requirement: Versioned source manifests
The system SHALL reject a retail fixture unless its manifest declares a stable dataset key, source name, source URI or local origin, license or usage note, retrieval date, encoding, expected schema, expected counts, file checksum, and transform version.

#### Scenario: Valid local basket snapshot
- **WHEN** the GBK basket files match the declared checksums, schema, and expected counts
- **THEN** the system imports 9,835 baskets, 43,367 lines, 169 products, and 10 categories with the manifest attached

#### Scenario: Source drift detected
- **WHEN** a source file checksum, encoding, required column, or invariant differs from the manifest
- **THEN** the import fails before mutating database or managed fixture state and reports the failed invariant

### Requirement: Field-level truth classification
The system SHALL classify imported values as `observed`, deterministic calculations as `derived`, and invented demonstration values as `synthetic`, and SHALL expose field lineage for each derived or synthetic record.

#### Scenario: Basket-grounded support case
- **WHEN** a support case is generated from an observed basket
- **THEN** product and basket membership are marked observed while customer wording, delivery state, issue reason, and resolution are marked synthetic unless another source proves them

#### Scenario: UCI cancellation
- **WHEN** an invoice identifier in the UCI snapshot begins with the documented cancellation prefix
- **THEN** cancellation is marked observed and any inferred cancellation reason remains synthetic or unknown

### Requirement: Offline and bounded lifecycle
The system SHALL seed, reset, and verify managed retail fixtures without network, LLM, embedding, vector database, or external service access and SHALL delete only records owned by the managed demo dataset.

#### Scenario: Repeated offline seed
- **WHEN** seed runs twice using unchanged managed snapshots
- **THEN** the second run reuses stable records, produces identical metrics, and creates no duplicates

#### Scenario: Ordinary data is present
- **WHEN** reset runs while ordinary-user retail or support records exist
- **THEN** the system preserves those records and removes only manifest-owned demo records

### Requirement: Data coverage disclosure
The system SHALL report source counts, usable and rejected rows, time/category/customer coverage, missingness, observed/derived/synthetic ratios, and dataset limitations without fabricating unavailable dimensions.

#### Scenario: Basket dataset has no time or price
- **WHEN** users inspect the local basket corpus
- **THEN** the coverage response marks time, price, customer, delivery, and after-sales fields unavailable instead of displaying generated values as observed
