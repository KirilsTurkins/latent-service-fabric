# Transactional keyed-state throughput

**Status: specified, not a new benchmark result.** Development implements
configured transactional state, bounded queries and host-owned commit/recovery
paths; see the [current architecture](../../docs/architecture/state-and-effects.md).
This directory's `benchmark.toml` still specifies a throughput campaign and does
not establish completion of Phase 4 qualification.

## Bounded backing-store control

Run the embedded file control from the checkout on the intended measurement
host.

```bash
cargo run --locked --release -p latent-state --example state_throughput
```

The control creates a temporary redb file with a 32 MiB cap. It seeds 16 rows
of 128 bytes and uses five warm-up operations followed by 30 measured
operations per case. The cases cover durable commits, stale conflicts, fresh
point reads and bounded prefix scans. The JSON reports p50, p95 and p99
latencies, completed operation rates, logical value bytes and the file size
before and after the run. Record the source, redb build, operating system, filesystem and machine
with any retained result. The full campaign adds signed guests, dispatcher
faults, cache variants and execution-owner observations.

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
