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
The current selected-configuration calibration is the seven-run native-Linux
archive in
[`benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754`](../benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/CALIBRATION.md).
It records its published commit/tree and the explicit
prepared-cache/on-demand/COW configuration used by the matching profile and
soak. The August 30 packages were verified together by the authorized full
gate; all August 29 packages remain immutable historical evidence.

Create a new archive only from a clean worktree on one stable native-Linux host
or VM:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  /var/tmp/phase0-evidence/calibration
~~~

The calibration wrapper refuses WSL and detected containers, requires fresh
external output/build directories, requires a durable published commit/tree/ref,
and invokes the complete full-profile command seven times. It rejects an
execution checkout whose HEAD is not that exact published commit or whose tree
does not match. It captures before/after
virtualization, allocator, CPU frequency/power-policy where exposed, and
background-load observations. It does not change CPU policy, pin frequency, or
discard a run because its performance values are inconvenient.

For a calibration used to assess the selected issue-40 ordinary configuration,
the helper explicitly passes and records a prepared cache, `on-demand`
Wasmtime allocation, and initialized-memory COW enabled. Those values are part
of the comparison identity; an older calibration that does not record them is
not interchangeable by assumption.

Every archived run must use the same source commit, fixture digest, Rust/Cargo
and Wasmtime versions, target, build profile, configuration, CPU, logical CPU
count, memory, and kernel. Any failed hard check, malformed output, missing
run, or mismatch invalidates the aggregate. Correctness, topology, capacity,
containment, cleanup, and reclamation checks remain binary; aggregation never
turns them into statistical tolerances.

The first validated full-profile result defines the canonical hard-invariant
name set. Every later run must contain exactly that set once and pass every
member. Duplicate, missing, or unexpected check names invalidate the aggregate
instead of being silently omitted from its summary.

The aggregate includes minimum, median, maximum, median absolute deviation
(MAD), coefficient of variation (CV) where meaningful, samples, runs, and
run-level outlier flags for startup/preparation, cold/warm activation,
acquire/queue/release, timeout/cancellation overshoot, trap/recovery, cleanup,
throughput, RSS, virtual memory, threads, sockets, and file descriptors. It
also retains every raw full-profile document beneath its runs directory.

For Phase 1, compare the median of at least seven comparable candidate runs
with each metric's checked-in advisory noise band. A deterioration outside its
band is a regression candidate and needs a confirming second set; repeated
outside-band deterioration confirms the regression. An inside-band candidate
with at least seven valid comparable runs, stable environment, all hard
invariants passing, and no material run-level outlier is terminally **no
detectable regression** (or statistically indistinguishable). Insufficient
samples, environment instability/mismatch, material run-level noise/outliers,
or failed invariants invalidate the comparison and require a rerun after the
condition is resolved. These are regression-detection aids only, not
production SLOs or cross-machine claims.
Shared hosted CI must never fail on these fragile microbenchmark bands; it may
continue to run only the deterministic correctness smoke profile.

## Native-Linux long-running resource plateau soak

Issue #39 has retained a separate heavy native-Linux proof of bounded
steady-state under fresh-store activation work. It is not part of the
pull-request smoke profile. A replacement or revalidation run must use the
final Phase 0 configuration:

```bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --published-source-ref <durable-branch-or-tag> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/soak
```

The command requires a clean native Linux host or VM and refuses WSL,
containers, unavailable `/proc` probes, unavailable validation fixtures or
toolchain, source-tree mismatch, and an existing output directory. It starts
at least three independent processes. A normal run cannot lower its workload:
each process has at least 1,000 warm-up activations excluded from growth
analysis and 100,000 normal measured fresh-store activations. Every measured
batch contains success, declared-domain-error, trap, timeout, cancellation,
memory-pressure, and immediately following cause-specific recovery work. Both
real at-capacity and real bounded-queue activation batches run at least every
ten measured batches.

The Rust probe samples each completed batch and fails immediately if topology
or any logical resource fails to return to baseline: active/available/
quarantined cells and queue depth; cancellation registrations and running
invocations; live stores, host states, component instances, temporary buffers,
and cancellation probes; log and prepared-cache entries/bytes; and the bounded
backend timing-store occupancy. It records RSS, VM, PSS and private mappings
where `/proc/self/smaps_rollup` exposes them, plus process/child/thread/FD and
open/listening socket counts. Allocator-internal statistics are deliberately
reported as unsupported until a safe allocator-specific probe is configured.

`aggregate.json` retains every raw file hash, schema, exact final source/tree,
component digest, command profile, run count, host provenance, interval method,
limits, unsupported probes, rolling ranges, peaks, final-window deltas,
Theil-Sen late slopes, post-release state, and shutdown state. New raw runs
also retain pre-runtime and post-warm-up process snapshots: the final measured
FD count must not exceed the post-warm-up baseline, and post-release/post-shutdown FDs
must not exceed that pre-runtime baseline. It validates terminal
process/child/thread/socket topology, and uses issue 38's RSS advisory noise
band only when CPU, memory, kernel, virtualization, toolchain, allocator,
fixture, and relevant execution configuration—including prepared-cache
enablement, Wasmtime allocator mode, and initialized-memory COW—are proved
matched. A missing or mismatched identity blocks the calibrated comparison and
authorization. A material
late-window growth or topology result remains failed and must identify a
retaining subsystem using heap/allocator/process tooling or a focused issue;
the noise allowance must not be raised to clear it. Robust cross-run
peak/delta outliers are separately retained as diagnostic variability; they
become a failure only when the same metric breaches its calibrated
late-window material-growth rule.

The retained post-issue-40 raw archive is
[`native-linux-2026-08-30-52ac4754`](../benchmarks/phase0/soak/native-linux-2026-08-30-52ac4754/README.md), measured from
durable source commit `52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
and tree `cac3ececdbd0b5734691c30c0283fccff169a5f5`. Its three complete processes
pass all hard invariants, raw/host reconciliation, explicit release/shutdown
topology, the complete descriptor lifecycle, and calibrated late-window
RSS/PSS/private/VM analysis. The raw archive is losslessly checksummed and the
aggregate applies the matching seven-process calibration without inference. It
is evidence input for the authorized full gate, not an authorization decision
by itself.

This retained result is an input to the completion gate, not an authorization
receipt. A current clean checkout must still satisfy the gate's exact
execution-identity and fresh-baseline checks before Phase 1 is authorized.

If the aggregate reports material growth, rerun the same command with
`--retaining-subsystem <name>` and/or `--followup-issue <URL-or-number>` after
collecting heap/allocator/process evidence. Those values document diagnosis;
they do not turn a growing run into a pass or loosen the calibrated allowance.

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
August 30 native-Linux calibration, profiling, soak, and full-gate receipt are
the current checked reference evidence; do not replace them with measurements
from a materially different environment.

`benchmarks/phase0/raw-results.json` and `benchmarks/phase0/BASELINE.md` are
generated from the same historical full-profile run. The August 30
native-Linux calibration archive is the Phase 1 comparison reference, and the
fresh authorizing baseline is retained with the August 30 gate receipt.

Reference files must not be replaced with measurements from a materially different CPU, memory size, OS/kernel, Rust/Wasmtime toolchain, target, build profile, fixture digest, pool topology, budget, threshold, or sample configuration without documenting the new environment and reason.

## Unsupported conclusions

The baseline does not support conclusions about production SLOs, competitive performance, cluster scaling, 100,000-service density, state throughput, remote-call latency, networking, autoscaling, long-duration leaks, or call-graph fusion. Those remain later-phase work.
