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

- [CALIBRATION.md](../benchmarks/phase0/calibration/native-linux-2026-08-27/CALIBRATION.md)
  is the concise seven-run report;
- [aggregate.json](../benchmarks/phase0/calibration/native-linux-2026-08-27/aggregate.json)
  contains dispersion statistics, outlier findings, environment/configuration,
  advisory bands, and the hard-invariant summary;
- [runs/](../benchmarks/phase0/calibration/native-linux-2026-08-27/runs)
  retains every individual full-profile raw result, per-run report, host
  observation, and command status.

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
4. rerun an inconclusive result, including any result inside the noise band,
   with material run-level noise/outliers, or with insufficient comparable
   runs;
5. preserve hard invariants as binary checks. A topology, capacity,
   containment, cleanup, or reclamation failure cannot be statistically
   tolerated.

Bounded-cache configuration and reclamation remain strict invariant checks;
Phase 1 must compare them against their recorded configured bounds rather than
turning cache growth into an advisory statistical tolerance.

A candidate deterioration beyond an advisory band is a regression candidate,
not an automatic production conclusion. It requires a second comparable set
for confirmation. Shared hosted CI may run deterministic correctness smoke
coverage, but must not fail on these microbenchmark bands.

## Remaining limitations

This evidence demonstrates only the Phase 0 spike under its documented
workload. It does not establish production API behavior, dormant-service
density, long-duration soak behavior, remote-call performance, cluster
scaling, or release SLOs. Those obligations remain with the Phase 1 work and
its completion gate.
