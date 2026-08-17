# Transactional keyed-state throughput

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
