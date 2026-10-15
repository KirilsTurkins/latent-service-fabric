# Transactional keyed-state throughput

**Status: specified, not a new benchmark result.** Development implements
configured transactional state, bounded queries and host-owned commit/recovery
paths; see the [current architecture](../../docs/architecture/state-and-effects.md).
This directory's `benchmark.toml` still specifies a throughput campaign and does
not establish completion of Phase 4 qualification.

[Userfault-pager research](../../research/userfault-pager/evaluation-plan.md)
defines a separate comparison against these existing selective operations,
explicit chunks and kernel-managed mappings. Page-fault/dirty counts cannot
substitute for logical read/write budgets, conflict checks or commit metrics.

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
