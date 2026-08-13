# Source inventory

Last curated: 2026-07-31.

| Source | Scope | Freshness | Authority | Coverage / gaps |
|---|---|---|---|---|
| Kairo iPhone HealthKit bridge | Authorized HealthKit samples, deletions, source, device, metadata | event-driven subject to iOS scheduling | primary implementation | 172 retained anchored streams in the completed import; clinical records and medication APIs remain separate opt-ins |
| Neon `health_changes` ledger | Idempotently received raw changes | after acknowledged upload | primary system of record | current prototype is single-owner; reinstall/device duplicates are resolved in the current-observation view |
| User storage audit | Per-type counts and table sizes after full import | 2026-07-31 snapshot | direct database result | roughly 237,912 retained changes and about 200 MB; useful for capacity, not health meaning |
| Apple HealthKit documentation | Query, aggregation, sleep, State of Mind, source/device, and time semantics | consult on SDK changes | primary vendor source | availability and identifiers vary by OS/SDK |
| HL7 FHIR R4 Observation | effective-time versus issued-time distinction | stable R4 reference | healthcare standard | informs semantics; Kairo does not claim to be a FHIR server |
| Intensive longitudinal affect research | within-person mood modelling and temporal validation | literature snapshot | peer-reviewed research | cohort findings guide method, not personal conclusions |

## Known gaps

- No dedicated medication or clinical-record collector yet.
- HealthKit cannot reveal which individual read permissions were denied.
- iPhone/Watch delivery is event-driven but not a real-time SLA.
- Automatic incremental feature rebuilding after each ingest is not yet wired; the deterministic rebuild is implemented.
- Factor training is explicit and reproducible; scheduled recalibration still requires sufficient State of Mind labels and runtime orchestration.
- Attention, Work, Connection, and Story sources are outside this HealthKit semantic package.

## Refresh triggers

Refresh this inventory when the HealthKit catalog changes, a new source family is added, Apple changes semantics, database volume materially shifts, or the feature/model version changes. A weekly source poll is appropriate once external sources and scheduled jobs become active.
