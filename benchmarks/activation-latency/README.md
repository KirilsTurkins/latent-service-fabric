# Cold and warm activation latency

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
