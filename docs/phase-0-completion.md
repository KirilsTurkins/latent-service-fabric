# Phase 0 completion report

**Gate status:** Open. This report consolidates evidence for the Phase 0 gate;
it does not authorize Phase 1 until every dependency of issue 25 is complete.

## Calibrated performance and resource reference

The initial issue-24 full-profile files
[benchmarks/phase0/raw-results.json](../benchmarks/phase0/raw-results.json)
and
[benchmarks/phase0/BASELINE.md](../benchmarks/phase0/BASELINE.md)
are retained as historical WSL2 observations. They are not used as the
native-Linux variance reference.

Issue 38 establishes the calibration reference:

- [CALIBRATION.md](../benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/CALIBRATION.md)
  is the concise seven-run report;
- [aggregate.json](../benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json)
  contains dispersion statistics, outlier findings, environment/configuration,
  advisory bands, and the hard-invariant summary;
- [runs/](../benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/runs)
  retains every individual full-profile raw result, per-run report, host
  observation, and command status.

The reference was rerun from the durable published commit
[`49e24fdbee1a3cde1a09fdb3bf8dcf640cc956c3`](https://github.com/KirilsTurkins/latent-service-fabric/commit/49e24fdbee1a3cde1a09fdb3bf8dcf640cc956c3).
That exact source revision is retained independently on
[`benchmark/phase0-calibration-source-2026-08-27`](https://github.com/KirilsTurkins/latent-service-fabric/tree/benchmark/phase0-calibration-source-2026-08-27).
Its aggregate and every host observation record that commit's Git tree
`88e8875b7be7e46b4702c15d5c8c2f26c1e4a037`, the local execution commit, and
verified tree equality. The prior native-Linux archive remains unchanged as
superseded audit evidence because its SHA was not reachable.

The calibration invokes the existing full profile without weakening fixture
validation or hard topology, capacity, containment, cleanup, and reclamation
checks. It records the native-Linux environment, virtualization, allocator
observation, CPU/frequency policy where available, and background load. Its
statistics are observational and do not create production SLOs, capacity
commitments, or cross-machine claims.

## Required Phase 1 use

Issue 16 must compare productionized results against this calibration; it must
not reset the performance/resource reference after productionization. For
startup, preparation, cold/warm activation, cleanup, queueing, throughput,
RSS, and virtual memory, it must:

1. retain at least seven independent full-profile candidate runs and their raw
   provenance;
2. establish material equivalence of CPU, logical CPU count, memory, kernel,
   virtualization, Rust/Cargo/Wasmtime versions, target, build profile,
   allocator, fixture digest, and configuration;
3. compare the median of per-run representatives with the metric-specific
   advisory band in aggregate.json;
4. record **no detectable regression** (or statistically indistinguishable) as
   the terminal result for an inside-band candidate with at least seven valid
   comparable runs, a stable environment, all hard invariants passing, and no
   material run-level outlier;
5. rerun an inconclusive result caused by insufficient samples, environment
   instability/mismatch, material run-level noise/outliers, or failed hard
   invariants after the invalid condition is resolved; and
6. classify outside-band deterioration as a regression candidate, require a
   second matched set, and confirm the regression only when that second set
   also deteriorates outside the band;
7. preserve hard invariants as binary checks. A topology, capacity,
   containment, cleanup, or reclamation failure cannot be statistically
   tolerated.

Bounded-cache configuration and reclamation remain strict invariant checks;
Phase 1 must compare them against their recorded configured bounds rather than
turning cache growth into an advisory statistical tolerance.

A candidate deterioration beyond an advisory band is not an automatic
production conclusion: it requires the second comparable set above for
confirmation. Shared hosted CI may run deterministic correctness smoke
coverage, but must not fail on these microbenchmark bands.

## Execution hot-path profiling and optimization handoff

Issue 40 adds a separate native-Linux `perf` plus Heaptrack evidence workflow:
[the profiling handoff](phase-0-hot-path-profiling.md). It profiles the real
shared Phase 0 composition across cold preparation, first and warm activation,
failure containment/recovery, cleanup, and at-capacity/bounded-queue
contention. Every profile retains a passing full baseline document, exact
command, raw tool data, and symbolized CPU/allocation reports; an incomplete
tool artifact or a failed, missing, duplicate, or unexpected hard invariant is
invalid rather than silently omitted.

The accepted native-Linux archive is
[native-linux-2026-08-27-35a9944](../benchmarks/phase0/profiling/native-linux-2026-08-27-35a9944/README.md),
captured from durable source commit `35a9944f134098d4ea3e1f3859b9e9bf80d9a3ad`
and tree `316357dce997c33b25d230a84adbcf11dffc1097`. It retains a compact
machine-readable aggregate and concise report alongside a lossless,
checksummed archive of every raw CPU/allocation trace and full-process run.
The six Heaptrack reports each record 2.82 KiB of process-exit TLS/JIT/CLI
residue; this is retained for review, while every activation cleanup,
resource-reclamation, and runtime-thread invariant passes.

The bounded matrix measures fixed worker/cell ratios, bounded preparation reuse
versus cold preparation, on-demand versus pooling allocation, and COW
initialized-memory alternatives. The default remains the existing fixed
2-worker/2-cell, on-demand, COW-enabled configuration with one bounded prepared
component and fresh invocation-owned stores, host state, import tables,
instances, limiters, and activation contexts. Pooling, when profiled, is capped
to the fixed cell capacity and retains zero linear memory after a store drops.
No runtime optimization is adopted from a faster single/small set: adoption
requires at least seven comparable runs, issue-38 calibrated-noise clearance or
an explicit architectural benefit, bounded fixed/peak memory, and every hard
invariant passing. The current decision record retains the Phase 0 default,
defers scheduler ratios to #8, Wasmtime policy/cache/value work to #9,
lifecycle-envelope changes to #11, and rejects store/instance reuse and
untrusted AOT/cache/snapshot/native-execution shortcuts in Phase 0.

This handoff is optimization evidence only; it does not establish production
SLOs or cross-platform claims. Issue 39 must still execute its three independent
native-Linux 100k-activation soak processes against this final configuration
before the Phase 0 completion gate can close.

## Remaining limitations

This evidence demonstrates only the Phase 0 spike under its documented
workload. It does not establish production API behavior, dormant-service
density, long-duration soak behavior, remote-call performance, cluster
scaling, or release SLOs. Those obligations remain with the Phase 1 work and
its completion gate.
