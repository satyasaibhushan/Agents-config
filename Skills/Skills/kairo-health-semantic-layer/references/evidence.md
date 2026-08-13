# Evidence register

## Primary specifications

- Apple, Executing statistics collection queries: https://developer.apple.com/documentation/healthkit/executing-statistics-collection-queries
- Apple, Sleep analysis: https://developer.apple.com/documentation/healthkit/hkcategorytypeidentifier/sleepanalysis
- Apple, Sleep analysis values: https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis
- Apple, State of Mind: https://developer.apple.com/documentation/healthkit/hkstateofmind
- Apple, Source revision and device provenance: https://developer.apple.com/documentation/healthkit/hksourcerevision and https://developer.apple.com/documentation/healthkit/hkdevice
- HL7 FHIR R4 Observation definitions: https://hl7.org/fhir/R4/observation-definitions.html

## Method references

- Within-person affect prediction using intensive longitudinal data: https://pmc.ncbi.nlm.nih.gov/articles/PMC10131982/
- Person-specific prediction of affective states: https://pmc.ncbi.nlm.nih.gov/articles/PMC11574068/

## Interpretation notes

- Apple defines cumulative and discrete statistics differently; aggregation follows the per-signal catalog rather than a universal average.
- Apple sleep stages are overlapping interval/category records. Kairo reconstructs a wake-day episode and prevents overlapping sources from multiplying duration.
- State of Mind distinguishes daily mood from momentary emotion and carries valence plus optional labels/associations. It is direct self-report evidence.
- FHIR's separation of effective time and issued time supports keeping event time separate from ingestion time.
- The research supports person-specific, longitudinal validation. It does not establish that any Kairo feature causes mood for this owner.
