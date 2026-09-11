# Cold and warm activation latency

Phase 1 measurements and the extension cover selected cold/warm cases; see the [completed results](../../docs/phase-1-extension-completion.md). The metrics and variants below define the broader benchmark program, not a claim that every cache state has been measured.

## Required metrics

- `resolve_micros`
- `admission_micros`
- `materialize_micros`
- `instantiate_micros`
- `execute_micros`
- `total_micros`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
