# Cross-node invocation

This is a future cross-node benchmark specification. Phase 1 delivers authenticated loopback invocation on a standalone node; the Docker/Kubernetes comparisons do not implement LSF cluster routing.

## Required metrics

- `calls_per_second`
- `p50_micros`
- `p95_micros`
- `p99_micros`
- `transport_bytes`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
