# Semantic layer

## Entities and grains

| Entity | Grain | Canonical identifier |
|---|---|---|
| Source observation | one HealthKit sample version received through one bridge device | owner + device + sample UUID |
| Current observation | newest received sample version, including deletion state | owner + sample UUID |
| Signal definition | one Apple type mapped to Kairo semantics | HealthKit type identifier |
| Daily feature | one statistic for one personal day | owner + date + feature + statistic + version |
| Daily profile | compact feature document for one personal day | owner + date + version |
| Factor score | one lagged feature/target/horizon/model evaluation | owner + target + horizon + feature + lag + versions |
| Insight | one bounded conclusion with evidence and expiry | owner + insight UUID |

## Canonical time

- `start_at`/`end_at`: effective clinical or behavioural interval.
- `received_at`: arrival at Kairo; use only for freshness and sync operations.
- `personal_date`: effective time converted to owner IANA time zone.
- Sleep episode: assigned to local wake date.
- Mood: remains at its event time; daily and momentary kinds are not merged silently.

## Feature semantics

- Cumulative signals use sum.
- Discrete signals use mean/min/max or latest according to the signal catalog.
- Category signals use counts or duration after value-aware reconstruction.
- Overlapping sleep sources are deduplicated by selecting the source with the greatest stage-specific coverage.
- Baseline variants use the prior 28 personal days only and require at least seven observations.
- Conflicting units, incomplete source coverage, and impossible values generate quality flags rather than coerced values.

## Mood target and factor score

State of Mind valence, kind, labels, and associations define declared mood evidence. A factor score is specific to target, horizon, lag, feature version, model version, and evidence period.

`k = direction × normalized out-of-sample gain × stability × sqrt(coverage)`

Do not compare `k` values from different target/horizon definitions as if they measure the same relationship. `k` is predictive ranking evidence, not a causal coefficient.

## Join paths

- Current raw audit: `health_current_observations.type_identifier = health_signal_definitions.type_identifier`.
- Daily feature to profile: owner, `personal_date`, calculation version.
- Factor to daily feature: owner, `feature_key`, feature version; apply the stored lag relative to target day.
- Insight evidence: use `evidence_json` plus start/end dates, then verify the referenced feature/model versions still match.

## Approved assistant surfaces

- `/api/health/intelligence/day`
- `/api/health/intelligence/trend`
- `/api/health/intelligence/context`
- `/api/health/intelligence/catalog`

These routes require the signed owner session. Raw ledger and arbitrary SQL access are not assistant surfaces.

## Prohibited interpretations

- ingestion count as activity count;
- upload time as event time;
- absence as zero or denied permission;
- correlation or prediction as causality;
- low-confidence evidence as a medical diagnosis;
- population thresholds without unit, provenance, and personal context.
