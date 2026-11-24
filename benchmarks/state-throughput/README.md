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
point reads, bounded prefix scans and clean reopen with verification of the
last committed value. The JSON reports p50, p95 and p99
latencies, completed operation rates, logical value bytes and the file size
before and after the run. The pinned-view case times another 30 commits while
the original snapshot remains readable. It checks that compaction refuses the
live view, then records bounded compaction I/O, file growth and scratch limits
after that view retires. Reopen checks the latest committed value after
compaction. Record the source, redb build, operating system, filesystem and
machine with any retained result. The full campaign adds signed guests,
dispatcher faults, cache variants and execution-owner observations.

[Userfault-pager research](../../research/userfault-pager/evaluation-plan.md)
defines a separate comparison against these existing selective operations,
explicit chunks and kernel-managed mappings. Page-fault/dirty counts cannot
substitute for logical read/write budgets, conflict checks or commit metrics.

## Mixed Rust guest control

Build the maintained transaction aggregate for the pinned compiler and run the
existing native RPC fixture. Use a private filesystem for the fixture store and
record the source, component, engine and machine alongside the JSON sample.

```bash
guest_root=$(mktemp -d)/transaction-guest
python3 tools/compile_transaction_guests.py --language rust --output "$guest_root"
LSF_TRANSACTION_GUEST_ROOT="$guest_root" cargo test --locked -p latent-wire --lib   phase4::local_transaction::tests::mixed_queries:: -- --ignored --nocapture --test-threads=1
```

The control reads an original view while a write is paused, then uses each
commit's version as the minimum for a fresh query. It times 24 successful
commits, queries and original-result replays with two activation cells and
a paused dispatcher. The assertions check the final business value, one
durable command, result and effect per commit, and physical guest cleanup.
The p50 and p99 values cover each complete local RPC call. This trusted-local
profile has its own compiler and native runtime costs. Signed publication and
live provider costs are measured in their respective campaigns.

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
