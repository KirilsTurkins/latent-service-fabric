# Phase 0 activation, containment, and resource baselines

The Phase 0 baseline records reproducible observational evidence for issue #24. It is not a production benchmark, service-level objective, competitive comparison, cluster-capacity model, or Phase 1 API.

## Commands

Run the deterministic CI-sized profile:

```bash
tools/run_phase0_baselines.sh smoke target/phase0-baseline/smoke
```

Run and refresh the checked-in full-profile reference:

```bash
tools/run_phase0_baselines.sh full benchmarks/phase0
```

Both commands run `tools/validate_contracts.sh` first. Missing Rust Wasm targets, `wasm-tools`, Buf, validator dependencies, generated capsules, or containment fixtures therefore fail the command rather than silently skipping measurements.

## Native-Linux variance calibration

The original checked-in full-profile result is a historical WSL2 observation.
The Phase 1 comparison reference is the seven-run native-Linux calibration in
[benchmarks/phase0/calibration/native-linux-2026-08-27](../benchmarks/phase0/calibration/native-linux-2026-08-27).

Create a new archive only from a clean worktree on one stable native-Linux host
or VM:

~~~bash
tools/run_phase0_calibration.sh benchmarks/phase0/calibration/native-linux-YYYY-MM-DD
~~~

The calibration wrapper refuses WSL and detected containers, requires a new
output directory, fixes every run to the current commit, and invokes the
complete full-profile command seven times. It captures before/after
virtualization, allocator, CPU frequency/power-policy where exposed, and
background-load observations. It does not change CPU policy, pin frequency, or
discard a run because its performance values are inconvenient.

Every archived run must use the same source commit, fixture digest, Rust/Cargo
and Wasmtime versions, target, build profile, configuration, CPU, logical CPU
count, memory, and kernel. Any failed hard check, malformed output, missing
run, or mismatch invalidates the aggregate. Correctness, topology, capacity,
containment, cleanup, and reclamation checks remain binary; aggregation never
turns them into statistical tolerances.

The aggregate includes minimum, median, maximum, median absolute deviation
(MAD), coefficient of variation (CV) where meaningful, samples, runs, and
run-level outlier flags for startup/preparation, cold/warm activation,
acquire/queue/release, timeout/cancellation overshoot, trap/recovery, cleanup,
throughput, RSS, virtual memory, threads, sockets, and file descriptors. It
also retains every raw full-profile document beneath its runs directory.

For Phase 1, compare the median of at least seven comparable candidate runs
with each metric's checked-in advisory noise band. A deterioration outside its
band is a regression candidate and needs a confirming second set. A result
inside its band, one with material run-level noise/outliers, or one with fewer
than seven comparable runs is inconclusive and must be rerun. These are
regression-detection aids only, not production SLOs or cross-machine claims.
Shared hosted CI must never fail on these fragile microbenchmark bands; it may
continue to run only the deterministic correctness smoke profile.

## Exact issue-23 executable path

Before retained measurements begin, the runner repeatedly launches:

```text
latentd phase0-spike invoke-once
```

Each cold launch uses the staged containment capsule and the same worker, pool, queue, memory, fuel, and timeout configuration as the retained benchmark. The complete issue-23 JSON result is retained in `raw-results.json`. The executable-probe set also runs exact trap and timeout commands plus exact `verify-recovery` post-trap recovery. Every sample must report unchanged topology and a clean shutdown.

These fresh-process samples provide the cold-activation distribution and exercise success, failure, and recovery semantics from issue #23. The retained benchmark does not reconstruct those components: both binaries call the shared internal Phase 0 composition API for runtime creation, artifact loading, preparation, bounded cache/log configuration, bindings, and activation-runner construction.

## Startup and readiness

The parent process captures a wall-clock timestamp immediately before spawning `phase0-baseline`. The child reports readiness only after Tokio worker lifecycle hooks observe exactly the configured worker count and the fixed pool reports its configured capacity. No fixed readiness sleep is used.

The output distinguishes:

- external process launch to runtime/pool readiness;
- Rust entry to runtime/pool readiness;
- capsule validation and component loading;
- Wasmtime engine/backend construction;
- component preparation;
- Rust entry to retained invocation readiness;
- prepared-component release.

## Activation phase timings

The retained runner uses a transparent pool wrapper and backend boundaries recorded inside the real `Phase0WasmtimeBackend`. Every raw activation sample records:

- immediate acquisition or bounded-queue wait;
- Wasmtime-reported contained guest execution and the typed guest-call boundary (which includes Wasmtime's automatic canonical-ABI post-return);
- setup and in-guest host-import work as separate observations;
- host-visible post-call result accounting after that completed post-return boundary;
- store/instance/host-state/temporary-buffer reclamation;
- outcome classification and return of the reusable proof;
- total backend call to the reusable-proof boundary;
- the legacy backend residual interval;
- cell release or quarantine disposition;
- combined post-invocation cleanup;
- total invocation latency.

`post_invocation_cleanup_micros` is the authoritative cleanup metric: it begins at the host-visible completion of the typed guest call, after Wasmtime's automatic canonical-ABI post-return, and sums post-call result accounting, activation-resource reclamation, outcome classification, reusable-proof return, and cell disposition. The legacy `backend_resource_cleanup_micros` residual remains for trend comparison only; it includes setup and host work and is explicitly not presented as isolated cleanup latency.

## Cold, warm, containment, and recovery distributions

Cold echo samples come from independent launches of the exact issue-23 executable. Warm samples use one retained preparation. Domain error, trap, timeout, cancellation, and memory pressure each have distinct raw scenarios and are immediately followed by separately labelled recovery scenarios:

- `recovery_after_domain_error`;
- `recovery_after_trap`;
- `recovery_after_timeout`;
- `recovery_after_cancellation`;
- `recovery_after_memory_pressure`.

Minimum, nearest-rank P50/P95/P99, maximum, and mean are emitted for latency and cleanup measurements. The full profile uses multiple cold launches and repeated containment/recovery sequences; a single measurement is never presented as a distribution.

## Capacity and bounded queue saturation

Two end-to-end activation throughput modes execute through the complete activation runner and Wasmtime backend:

1. exactly `pool_capacity` concurrent delayed echoes;
2. exactly `pool_capacity + pool_queue_capacity` concurrent delayed echoes.

A concurrent pool monitor records maximum active leases and queue depth. The at-capacity mode fails unless it observes `active_leases == pool_capacity` and `queue_depth == 0`; the bounded-queue mode fails unless it observes both configured bounds. Queued activation acquire-wait, total latency, batch latency, and throughput are reported separately for each mode.

For both runs, a benchmark-only gate pauses real leases immediately after the shared pool grants them and before those real activation runners enter Wasmtime. It releases only after the raw pool observes the mode's required state: capacity with no queued waiter, or capacity plus the bounded queue. This prevents CPU-bound delayed guests from serializing the at-capacity measurement or starving the scheduler before queue-saturation waiters can enqueue; it creates no synthetic leases or backend results, and the raw acquisition timing remains separate from the coordination pause.

The lower-level fixed-pool probe remains separate. It measures direct acquire, queued wait, release, overflow rejection, and acquire/release throughput without presenting those operations as activation throughput.

## Topology and bounded-growth invariants

Structured topology fingerprints are recorded before capsule/component loading, after preparation, after completed workloads, after prepared-component release, and after runtime shutdown. They include:

- process and child-process count;
- OS thread count;
- lifecycle-observed Tokio worker count;
- open and listening socket count;
- fixed-pool capacity, availability, active leases, queue depth, and quarantine count;
- file descriptors, RSS, and virtual memory;
- runner cancellation and invocation counters;
- prepared-cache entries and bytes;
- live stores, host states, component instances, temporary buffers, and cancellation probes.

The configured Tokio worker count, process count, sockets, listeners, and structured cell state must remain stable across loading and repeated calls. One bounded Wasmtime epoch-ticker thread may appear during engine construction; the post-preparation OS-thread count must then remain constant.

Every completed activation must return active leases, waiters, cancellation registrations, running invocations, live stores, host states, component instances, temporary buffers, cancellation probes, retained logs, and quarantines to baseline. RSS and file descriptors must remain within the recorded finite allowances.

## Checked-in evidence

The original top-level baseline files remain historical WSL2 evidence. The
native-Linux aggregate and raw archive are separate reference evidence; do not
replace either with measurements from a materially different environment.

`benchmarks/phase0/raw-results.json` and `benchmarks/phase0/BASELINE.md` are generated from the same historical full-profile run. The native-Linux calibration archive is the Phase 1 comparison reference.

Reference files must not be replaced with measurements from a materially different CPU, memory size, OS/kernel, Rust/Wasmtime toolchain, target, build profile, fixture digest, pool topology, budget, threshold, or sample configuration without documenting the new environment and reason.

## Unsupported conclusions

The baseline does not support conclusions about production SLOs, competitive performance, cluster scaling, 100,000-service density, state throughput, remote-call latency, networking, autoscaling, long-duration leaks, or call-graph fusion. Those remain later-phase work.
