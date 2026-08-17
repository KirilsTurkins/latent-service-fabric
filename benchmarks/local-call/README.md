# Inline versus isolated-local call chain

## Required metrics

- `calls_per_second`
- `p50_micros`
- `p95_micros`
- `p99_micros`
- `bytes_copied`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
