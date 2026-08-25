# Phase 0 activation, containment, and resource baselines

The Phase 0 baseline is a reproducible observational probe for the executable spike. It composes the real fixed cell pool, Wasmtime backend, prepared component, and activation runner in one retained process. It is not a production benchmark, service-level objective, competitive comparison, cluster-capacity model, or Phase 1 API.

## Commands

The deterministic CI-sized run is:

```bash
tools/run_phase0_baselines.sh smoke target/phase0-baseline/smoke
```

The heavier local run is:

```bash
tools/run_phase0_baselines.sh full target/phase0-baseline/full
```

Both commands run `tools/validate_contracts.sh` first. The benchmark therefore fails rather than skipping when the Rust Wasm targets, `wasm-tools`, Buf, validator dependencies, generated echo capsule, or containment component are unavailable. The runner builds `phase0-baseline` in release mode with `--locked`, stages the containment component with an exact SHA-256 capsule digest, and writes:

- `raw-results.json`: the machine-readable measurements, snapshots, distributions, checks, limitations, and conclusions.
- `BASELINE.md`: a concise report generated from the same raw document.

The checked-in snapshot under `benchmarks/phase0/` is a reference observation from the documented environment. New runs should be stored separately and compared only when their environment and configuration are materially equivalent.

## Measurement method

The harness records distinct durations for Rust process entry to fixed runtime/pool readiness, capsule validation and component loading, Wasmtime engine/backend construction, component preparation, and process entry to first-invocation readiness. It then retains one prepared backend and runner across:

1. one cold echo and a configurable warm-echo sample set;
2. repeated echo, declared domain error, trap, timeout, explicit cancellation, and memory-pressure cases;
3. a successful echo immediately after every failure;
4. direct fixed-pool acquire/release samples, capacity saturation, every bounded queue slot, one rejected overflow waiter, and concurrent acquire/release throughput;
5. concurrent delayed-echo batches with exactly the configured cell capacity.

Latency and interruption values are retained as raw samples and summarized with minimum, nearest-rank P50/P95/P99, maximum, and mean. Throughput is an observed operation count divided by measured batch wall time.

## Invariants and resource probes

At idle, after every activation or throughput batch, after prepared-component release, and after runtime shutdown, the harness records the available platform observations. The strict checked-in and CI baseline uses Linux `/proc` to record:

- process and child-process count;
- OS thread count;
- file-descriptor count;
- process-owned open socket descriptors and process-owned TCP/TCP6 listening sockets;
- resident-set and virtual-memory size;
- fixed-pool capacity, available cells, active leases, queued waiters, and quarantined cells;
- activation-runner cancellation registrations, running and total invocations, releases, quarantines, and disposition failures;
- prepared-cache entries, source bytes, and configured bounds;
- live Wasmtime invocations, stores, host states, component instances, temporary buffers, and cancellation probes.

A run fails when topology changes, an activation-owned resource remains live, the queue exceeds its configured bound, the cache exceeds its configured bound or does not clear on release, a failure degrades the next echo, timeout/cancellation overshoot exceeds the configured allowance, or RSS/file descriptors move outside the finite steady-state allowance. Cumulative `stores_created` is reported separately and is not treated as a live resource.

## Comparison rules and limitations

Compare observations only when CPU, total memory, OS and kernel, Rust and Cargo versions, Rust target, Wasmtime version, release/debug profile, repository commit, fixture digest, worker count, pool and queue capacity, budgets, timeout settings, sample counts, and probe support are recorded and materially equivalent.

Shared-host scheduling, CPU frequency, page-fault state, filesystem cache, allocator behavior, and runner virtualization add noise. Wasmtime or the allocator may retain a bounded arena after first use, so the resource gate tests a configured finite range and monotonic trend after warm-up rather than byte-for-byte RSS return. The harness does not make claims about autoscaling, clustered placement, stateful services, networking, long-duration leak behavior, or production concurrency.
