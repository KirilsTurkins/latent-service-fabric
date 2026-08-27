# Phase 0 execution hot-path profiling and Phase 1 handoff

This document records the method and decisions for issue 40. It turns the
finite Phase 0 baseline into an optimization handoff without treating a local
microbenchmark as a production SLO, cross-platform conclusion, or capacity
promise.

## Reference method

Run the profile set only from a clean worktree on a stable native-Linux host or
VM. The command rejects WSL and detected containers, requires `perf`,
`heaptrack`, and `heaptrack_print`, and fails if fixture validation or a Phase
0 hard invariant fails. These are open-source local tools; neither is required
for normal builds or pull-request CI.

First publish the exact source tree under a durable branch or tag, then run:

```bash
tools/run_phase0_hot_path_profiles.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  benchmarks/phase0/profiling/native-linux-YYYY-MM-DD
```

The wrapper builds a debuginfo-preserving release binary in an isolated target
directory, validates and stages the real containment fixture, creates the
exact executable parity probe (regenerating it for each worker/cell topology),
then invokes the same shared Phase 0 composition for every measurement. It
preserves `perf.data`, a symbolized
`perf report --stdio`, Heaptrack's native compressed raw filename, normal and
leak-only `heaptrack_print` output, exact commands, baseline raw results, and
Markdown baseline reports. The aggregate requires a nonzero Heaptrack
allocation-call total and a process-exit leak total, so unreadable compressed
data cannot be misreported as zero allocation. It rejects a profile that lacks
either tool's raw/report output, has a source-identity mismatch, a
missing/duplicate/unexpected hard check, or one failed hard check.

The workload set is intentionally biased toward each path while leaving the
real composition intact:

- cold preparation;
- first activation after preparation;
- steady warm echo execution;
- trap, timeout, cancellation, and memory-pressure containment/recovery;
- post-invocation cleanup and cell disposition; and
- at-capacity plus bounded-queue contention.

The profile aggregation retains the raw Phase 0 timing boundaries and maps
symbolized CPU/allocation evidence to capsule parsing/digest validation,
Wasmtime engine/component preparation, store/limiter/host-state/instance/import
construction, envelope/metadata work, WIT lifting/lowering and payload copies,
host context/log calls, result/diagnostic mapping, reclamation/disposition, and
pool/queue/runtime coordination. Automatic symbol matching is an index into
the retained reports; an unmatched category is never misreported as zero cost.

## Explicit experiment boundary

The default Phase 0 behavior is unchanged: a fixed 2-worker/2-cell topology,
on-demand Wasmtime allocation, initialized-memory COW enabled, one bounded
prepared component, and a fresh store, limiter, host state, activation context,
import table, and component instance for each activation.

The profile binary exposes only bounded experimental alternatives:

- 1/1, 2/2, 2/4, and 4/2 worker/cell ratios, exercised with tiny warm echoes
  and CPU-bound delayed-echo contention;
- default bounded preparation reuse versus independent cold preparation;
- on-demand allocation with COW disabled;
- pooling allocation with COW disabled or enabled; and
- the source-level allocation/copy boundaries surfaced by Heaptrack.

Pooling is never a hidden density optimization. Its configuration reserves at
most the selected fixed cell capacity (with finite component/core/memory/table
and async-stack counts), retains zero linear memory after a store drops, and is
recorded in the preparation key and raw configuration. This makes its
node-fixed mapping and peak-memory cost observable alongside latency and
throughput before any future adoption decision.

No profile command enables persistent AOT artifacts, provenance-sensitive
compiler caches, snapshots, store reuse, instance reuse, shared mutable guest
instances, or native execution.

## Decision rule

Every candidate run records cold/warm latency, at-capacity and queued
throughput, process RSS/VM/FD/thread/socket peaks, and the complete Phase 0
containment and reclamation proof. The aggregate reads the issue-38 native
Linux calibration band for matching metrics, but it refuses to call any
candidate adopted from fewer than seven comparable independent runs. A faster
single or small candidate set is an observation only.

A candidate may be adopted in Phase 0 only if it exceeds the calibrated noise
envelope (or has a separately documented architectural benefit), passes every
hard invariant, has bounded fixed/peak memory with no hidden topology change,
and does not take configuration/API ownership from Phase 1. Any adopted runtime
change requires a regenerated full Phase 0 reference and an auditable
comparison with the prior reference. The initial issue-40 archive deliberately
does not adopt a new runtime optimization; it records evidence and keeps the
measured default configuration for the required issue-39 soak.

## Decisions and ownership

| Candidate | Decision | Owner / rationale |
| --- | --- | --- |
| Existing fixed 2-worker/2-cell, on-demand/COW configuration | Adopt now (retain) | It is the bounded Phase 0 reference; issue 39 will soak it after this work lands. |
| One-entry bounded prepared-component cache | Adopt now (retain) | Immutable node-owned preparation state only; issue 9 owns general cache compatibility and eviction. |
| Worker/cell ratios | Carry as configurable Phase 1 experiment | Issue 8 owns fixed multi-class capacity, fairness, and scheduler policy. |
| Pooling allocator | Defer | Issue 9 must supply generalized bounded limits, density measurements, and reset/isolation proof. |
| COW initialized memory | Carry as configurable Phase 1 experiment | Issue 9 owns target-aware Wasmtime policy and a safe fallback. |
| Avoidable envelope/value allocations and copies | Defer | Issues 9 and 11 own the generic codec and lifecycle shapes; Phase 0 must not prematurely alter those contracts. |
| Store/instance reuse | Reject in Phase 0 | It would require a new reset/isolation proof; fresh stores and instances remain mandatory in issue 9. |
| Persistent AOT/compiler cache/snapshot/native execution | Defer to Phase 2 or later | It needs trusted provenance and supply-chain design, not a Phase 0 microbenchmark. |

Issue 8 inherits the fixed pool, bounded queue, and capacity evidence rather
than a selected ratio. Issue 9 inherits real Component Model CPU/allocation
profiles and owns engine policy, cache generalization, and value mapping. Issue
11 inherits the cleanup/lifecycle timing and evidence boundaries. None of those
tickets may weaken the Phase 0 fresh-store, fixed-topology, bounded-state, or
affirmative-cleanup proof.

## Limits

Profiles are finite and machine-specific. They do not establish production
SLOs, generic application performance, cross-machine performance, long-duration
leak freedom, catalog density, remote-call performance, or cluster scaling.
Issue 39 remains the required native-Linux 3x100k-activation plateau proof for
the final configuration.
