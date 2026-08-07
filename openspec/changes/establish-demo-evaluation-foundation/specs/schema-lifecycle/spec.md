## Purpose

Provide repeatable database creation and upgrades for both clean installations and existing local SQLite projects without ad-hoc schema drift.

## ADDED Requirements

### Requirement: Empty database upgrade
The system SHALL create the complete current application schema and record the active schema revision when upgrading an empty supported database.

#### Scenario: First startup on an empty SQLite database
- **WHEN** the application starts with a writable SQLite database containing no application tables
- **THEN** all required application tables and the schema revision marker are created before requests are accepted

### Requirement: Existing database adoption
The system SHALL adopt a recognized pre-migration database without deleting existing application records and SHALL apply all later revisions in order.

#### Scenario: Upgrade a recognized legacy SQLite database
- **WHEN** a database contains known application tables but no schema revision marker
- **THEN** the system brings known legacy columns to the baseline shape, records the baseline revision, and applies every later revision without losing existing rows

#### Scenario: Reject an unrecognized partial schema
- **WHEN** a database contains an incompatible or unrecognized subset of application tables
- **THEN** startup fails with a migration error that identifies the database as unsafe to adopt

### Requirement: Versioned forward and reverse changes
Every schema change after the baseline MUST define an ordered upgrade and downgrade operation.

#### Scenario: Inspect a post-baseline revision
- **WHEN** a migration revision adds or changes application schema
- **THEN** the revision contains both upgrade and downgrade behavior and declares the exact previous revision
