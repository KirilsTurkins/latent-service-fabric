# Transactional keyed-state throughput

This is a Phase 4 benchmark specification. Transactional keyed state and commit coordination are not implemented by the completed stateless Phase 1 runtime.

## Required metrics

- `transactions_per_second`
- `conflict_rate`
- `commit_p99_micros`
- `bytes_read`
- `bytes_written`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths
