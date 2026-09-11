# Derived composition performance

This is a research benchmark specification. Call-graph fusion has not been promoted into the completed Phase 1 runtime.

## Required metrics

- `unfused_p99_micros`
- `fused_p99_micros`
- `serialization_bytes_saved`
- `compile_micros`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
