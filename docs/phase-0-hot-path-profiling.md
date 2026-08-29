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
  --published-source-ref <durable-branch-or-tag> \
  --calibration-aggregate /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/profiling
```

Before it runs, the wrapper refreshes the supplied durable branch or tag (or,
when offline, explicitly records use of an existing `origin` tracking ref) and
rejects the run unless the supplied commit exists, resolves to the supplied
tree, and is reachable from that ref. It then verifies that the local execution
tree is identical to the published tree. Every raw command and host observation
retains the published ref/head plus source and execution identities. The
aggregate also requires every full, targeted, and candidate baseline document
to retain complete per-run host/toolchain context and rejects a mismatch with
the captured native-Linux host or full-invariant proof.

`--calibration-aggregate` is required; there is no fallback to a historical
checked-in calibration. Before creating profiling output, the wrapper
regenerates that aggregate from its sibling `runs/` directory and accepts it
only when every retained native-Linux full-profile run, hard invariant,
provenance record, configuration identity, metric comparison, source commit,
and source tree matches the supplied published source. Keep both calibration
and profiling output outside the source tree while collecting evidence.

The wrapper builds a debuginfo-preserving release binary in an isolated target
directory, validates and stages the real containment fixture, creates the
exact executable parity probe (regenerating it for each worker/cell topology),
then invokes the same shared Phase 0 composition for every measurement. It
preserves `perf.data`, a symbolized
`perf report --stdio`, Heaptrack's native compressed raw filename, normal and
leak-only `heaptrack_print` output, a compact checksum-bound Heaptrack
allocation-call/peak-byte attribution summary, exact commands, raw results,
and Markdown reports. The complete folded stacks are regenerated transiently
from the retained raw Heaptrack trace rather than checked in as hundreds of
megabytes of repetitive demangled text. The aggregate requires a nonzero Heaptrack
allocation-call total and a process-exit leak total, so unreadable compressed
data cannot be misreported as zero allocation. It rejects a profile that lacks
either tool's raw/report output, has a source-identity mismatch, a
missing/duplicate/unexpected hard check in the complete proof, or one failed
hard check.

The current native-Linux reference is
[native-linux-2026-08-29-a724a5e3](../benchmarks/phase0/profiling/native-linux-2026-08-29-a724a5e3/README.md).
It records durable source commit `a724a5e35234175f1001d1983e4411296ffa6b78`
and tree `c06ace2ae0f503495fa5bf87710ae5fc74c7ef50`. Its compact aggregate
and concise report are directly checked in; its complete raw profile tree is
losslessly retained with checksums in reassemblable `raw-evidence.tar.zst`
fragments. The Heaptrack
leak-only reports retain the observed process-exit residues rather than
claiming they are zero or an unproven per-activation leak.

The workload set is scenario-selective while leaving the real composition
intact. A separate uninstrumented `--mode full` proof retains the complete
canonical invariant set. The CPU and Heaptrack runs execute only the named
boundary, and the validator rejects a missing `--profile-workload`, duplicated
scenario semantics, or a targeted document used as a substitute for the full
proof:

- cold preparation;
- a direct same-key prepared-cache-reuse probe and an explicit cache-disabled
  cold control;
- first activation after preparation;
- steady warm echo execution;
- trap, timeout, cancellation, and memory-pressure containment/recovery;
- post-invocation cleanup and cell disposition; and
- at-capacity contention; and
- bounded-queue contention.

The profile aggregation retains per-workload quantitative attribution. It
reports both `perf report --no-children` CPU self percentage and inclusive CPU
percentage, plus Heaptrack folded allocation calls and peak bytes for every
required contributor category and a mandatory `unmatched_or_unknown` bucket.
Heaptrack folded stacks are root-to-leaf: the classifier walks from the
allocation leaf toward the root, skips allocator, generic-container, dynamic
loader, and async/runtime plumbing, then applies category precedence only to
the first remaining owner frame. It never lets an outer frame override that
owner. The categories are narrow and disjoint: result/diagnostic attribution
requires a direct mapping or rendering operation, not a generic `Result`,
`PlatformError`, or `GuestOutcome` type name. In particular, WIT/payload
attribution uses a matched WIT/canonical frame, never the generic word
`component`, `memcpy`, or `memmove`. It also records actual input and output
payload-flow byte counters without calling those bytes copied unless a narrow
WIT/copy symbol supports that claim. The reports cover capsule parsing/digest validation,
Wasmtime engine/component preparation, store/limiter/host-state/instance/import
construction, envelope/metadata work, WIT lifting/lowering and payload copies,
host context/log calls, result/diagnostic mapping, reclamation/disposition, and
pool/queue/runtime coordination. A category without direct profiler samples is
reported as **not observed at profiler resolution**, never as measured zero
cost; an unmatched category is retained and quantified rather than silently
dropped.

## Explicit experiment boundary

The default Phase 0 behavior is unchanged: a fixed 2-worker/2-cell topology,
on-demand Wasmtime allocation, initialized-memory COW enabled, one bounded
prepared component, and a fresh store, limiter, host state, activation context,
import table, and component instance for each activation.

The profile binary exposes only bounded experimental alternatives:

- 1/1, 2/2, 2/4, and 4/2 worker/cell ratios, exercised with tiny warm echoes
  and CPU-bound delayed-echo contention;
- default bounded preparation reuse versus independent cold preparation;
- an explicit cache-disabled, runner-scoped-no-reuse control alongside the
  bounded cache, so cold preparation is not inferred from phases in a cached
  process;
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
throughput, fixed runtime RSS/VM, preparation and post-release deltas, peak
RSS/VM/FD/thread/socket values, topology, per-run command/environment
provenance, and the complete Phase 0 containment and reclamation proof. The
unprofiled candidates retain the calibrated cooperative `yield_now()`
coordination method; only targeted profiler runs may record a one-millisecond
poll interval. The experiment matrix rejects fewer than three independently
retained full runs for each candidate; that minimum is still insufficient for
a Phase 0 adoption claim.

The aggregate reads the supplied fresh native-Linux calibration only after it
proves material equivalence of source, methodology, environment,
fixture/configuration and run count. A mismatched source/method/environment/
configuration or fewer than seven independent full runs is explicitly
**inconclusive** and cannot be labelled inside or outside the advisory band. A
faster single or small set is an observation only.

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
| Existing fixed 2-worker/2-cell, on-demand/COW configuration | Retain existing default; no new adoption | It is the bounded Phase 0 reference; issue 39 will soak it after this work lands. |
| One-entry bounded prepared-component cache | Retain existing setting; no new adoption | Immutable node-owned preparation state only; issue 9 owns general cache compatibility and eviction. |
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

## Archive integrity in CI

The native profiles remain a manual process; profiling tools are not installed
in shared CI. The deterministic Phase 0 workflow nevertheless runs the
reassembler unit tests and verifies the checked-in archive end-to-end: it joins
all fragments, checks the zstd stream, extracts it, and verifies the extracted
SHA-256 manifest. This protects the raw evidence transport without turning
machine-specific performance bands into CI gates.
