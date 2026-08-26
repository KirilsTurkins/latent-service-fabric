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

## Exact issue-23 executable path

Before retained measurements begin, the runner repeatedly launches:

```text
latentd phase0-spike invoke-once
```

Each launch uses the staged containment capsule and the same worker, pool, queue, memory, fuel, and timeout configuration as the retained benchmark. The complete issue-23 JSON result is retained in `raw-results.json`. Every sample must return the expected echo, report unchanged pre-load/post-activation topology, and prove a clean shutdown.

These fresh-process samples provide the cold-activation distribution and ensure that configuration validation, topology monitoring, preparation, cleanup, and result semantics from issue #23 cannot regress while a separately reconstructed benchmark still passes.

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

The retained runner uses transparent timing wrappers around the real `FixedCellPool` and `Phase0WasmtimeBackend`. Every raw activation sample records:

- immediate acquisition or bounded-queue wait;
- contained guest execution;
- total backend call to the reusable-proof boundary;
- backend resource-cleanup/host-overhead interval;
- cell release or quarantine disposition;
- combined post-invocation cleanup;
- total invocation latency.

The backend cleanup interval is the reusable-proof boundary minus Wasmtime’s guest wall-time measurement. It therefore includes bounded backend setup and host overhead in addition to destruction of activation-owned runtime resources. This limitation is recorded explicitly rather than presenting the value as pure destructor time.

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

A concurrent pool monitor records maximum active leases and queue depth. The saturation mode fails unless it observes both configured bounds. Queued activation acquire-wait, total latency, batch latency, and throughput are reported separately from the at-capacity mode.

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

`benchmarks/phase0/raw-results.json` and `benchmarks/phase0/BASELINE.md` are generated from the same full-profile run. The branch workflow runs the deterministic smoke gate first, then regenerates and commits those full-profile files to the PR branch. The evidence commit uses `[skip ci]` to avoid a workflow loop.

Reference files must not be replaced with measurements from a materially different CPU, memory size, OS/kernel, Rust/Wasmtime toolchain, target, build profile, fixture digest, pool topology, budget, threshold, or sample configuration without documenting the new environment and reason.

## Unsupported conclusions

The baseline does not support conclusions about production SLOs, competitive performance, cluster scaling, 100,000-service density, state throughput, remote-call latency, networking, autoscaling, long-duration leaks, or call-graph fusion. Those remain later-phase work.
