# Inline versus isolated-local call chain

This is a future benchmark specification for inline versus isolated-local service-to-service calls. Phase 1 delivers external invocation on a standalone node; these call-chain variants are not completed Phase 1 measurements.

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
