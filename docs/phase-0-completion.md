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

## Long-running resource plateau and leak resistance

Issue 39 now has a retained native-Linux soak harness at
[`tools/run_phase0_resource_soak.sh`](../tools/run_phase0_resource_soak.sh).
It is deliberately an explicit heavy command, separate from shared PR smoke
coverage. It records at least three independent processes, each with 1,000
excluded warm-up activations, 100,000 measured fresh-store activations, and
frequent real at-capacity and bounded-queue batches. Every batch must return
logical pool, runner, backend, log, cache, and timing-store state to its fixed
baseline before its raw interval sample is kept.

The companion aggregate records raw-file hashes and command/source provenance,
native-host observations, RSS/VM/PSS/private (where exposed), process/thread/
socket/FD topology, rolling ranges, final-window deltas, robust late-window
slopes, peaks, explicit release, and runtime shutdown. It applies the issue 38
calibrated RSS noise band only after CPU, memory, kernel, virtualization,
toolchain, allocator, fixture, and relevant configuration identity are proved
matched; a missing or mismatched identity is inconclusive. An unexplained
measured-window or release-to-shutdown FD increase, terminal topology change,
hard-invariant failure, missing batch, or calibrated material late-window
growth fails the aggregate. Robust cross-run peak/delta outliers are retained as diagnostic
variability; a stable late-window series inside its calibrated band is not
silently relabelled as a leak. A material-growth result requires
heap/allocator/process investigation and a retaining subsystem or focused
issue; the command never increases its allowance to make the result pass.

Issue 40's final ordinary Phase 0 configuration (bounded prepared cache,
on-demand Wasmtime allocation, initialized-memory COW enabled) has retained
raw evidence in the native-Linux archive
[`native-linux-2026-08-27-6250b978`](../benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/README.md).
Its three independent processes each completed 1,000 excluded warm-ups,
100,000 normal measured fresh-store activations, and 100 real batches of each
saturation mode. Every hard invariant, descriptor/topology check, explicit
prepared-component release, runtime shutdown check, and retained measured-
window/release-to-shutdown FD check passes. Strict revalidation does not apply
the issue-38 bands to this historical archive: that calibration lacks explicit
prepared-cache, Wasmtime allocator, and initialized-memory COW provenance,
while the soak host captures lack VM detection and allocator provenance. The
raw documents also predate the serialized pre-runtime and post-warm-up
descriptor baselines plus raw virtualization kind, so the complete lifecycle
cannot be independently revalidated. The raw late-window series and run-03 PSS outlier remain retained
for diagnosis, but the comparison is explicitly **inconclusive** and #39
remains open pending a fresh selected-configuration calibration and three-
process archive from the updated runner.

The wrapper requires `--final-configuration-commit` to equal the measured
reachable source commit, preventing a pre-final run from being reported as a
passing plateau result. This finite soak does not prove arbitrary-duration leak
freedom, production SLOs, multi-node behavior, or allocator-internal state not
exposed by the configured safe probes.

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
shared Phase 0 composition across cold preparation, direct prepared-cache
reuse, first and warm activation, failure containment/recovery, cleanup, and
separate at-capacity and bounded-queue contention paths. Every profile retains
a passing full baseline document, exact command, raw tool data, and symbolized
CPU/allocation reports; an incomplete tool artifact or a failed, missing,
duplicate, or unexpected hard invariant is invalid rather than silently
omitted.

The accepted native-Linux archive is
[native-linux-2026-08-27-de2337906](../benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/README.md),
captured from durable source commit `de2337906a4942e47611124a1c2217949abb58dc`
and tree `0a32896faa58da7f34662cbf3be97670d6d1de4c`. It retains a compact
machine-readable aggregate and concise report alongside a lossless,
checksummed archive of every raw CPU/allocation trace and full-process run.
The eight Heaptrack reports each record 2.82 KiB of process-exit TLS/JIT/CLI
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
SLOs or cross-platform claims. The retained issue-39 archive above executes
three independent native-Linux 100k-activation soak processes against this
final configuration, but its strict #38 comparison is inconclusive until a
fresh complete-provenance archive is collected; #39 remains one required input
to the still-open Phase 0 completion gate.

## Remaining limitations

This evidence demonstrates only the Phase 0 spike under its documented
workload. It does not establish production API behavior, dormant-service
density, remote-call performance, cluster scaling, or release SLOs. The
finite long-duration soak can demonstrate only a fully recorded matched-host
post-warm-up plateau, not arbitrary-duration leak freedom. The current
historical archive is not yet such a matched comparison; those obligations
remain with the Phase 1 work and its completion gate.
