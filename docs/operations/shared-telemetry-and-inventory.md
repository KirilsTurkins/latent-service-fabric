# Shared telemetry and live standalone node inventory

LSF observability is a node resource, not a service resource. The standalone node owns one bounded telemetry queue, one exporter task, one bounded local development sink, and one set of live inventory sources. Registering a dormant release does not create a per-service exporter, timer, thread, socket, process, queue, or execution host.

This implementation depends on the hardened Issue 36 contracts. `ActivationOutcome` and `GuestOutcome` carry successful returns, component-declared errors, and platform failures as three explicit variants. No media type, payload, error text, or service-specific constant is used to infer the outcome class.

## Executable composition

The real `latentd phase0-spike` path constructs:

1. one `Phase0NodeObservability` instance;
2. one `ObservedCellPool<FixedCellPool>` and one `ObservedExecutionBackend<Phase0WasmtimeBackend>`;
3. the actual `Phase0ActivationRunner` from those observed adapters;
4. one `ObservedActivationManager` around that runner; and
5. a bounded guest-log bridge from the Wasmtime node sink into the shared observer.

The existing machine-readable `invoke-once` and `verify-recovery` results include an `inventory` object. That object is collected after the activation and refreshed after prepared-component release, so the CLI exposes final live cell, queue, cache, pressure, health, route-generation, and topology state rather than a startup declaration.

## Lifecycle and correlation

The observer emits bounded lifecycle metrics and, while correlation exists, matching logs and spans for:

- receipt;
- resolution;
- admission;
- queueing;
- materialization;
- execution;
- cancellation;
- failure;
- completion; and
- cleanup.

Failure and completion records are emitted before the activation correlation is removed. Failure spans have `error` status, cancellation spans have `cancelled` status, and a failed completion is not marked `ok`. Guest logs are forwarded before terminal finalization, while the activation, tenant, service, trace, release/revision, and route-generation context is still available.

The adapter calls are fallible. The production default remains failure-isolated: a full or closed telemetry queue returns `Ok(false)` and does not alter the activation result. Tests may set `fail_on_drop`; the resulting error is then propagated through the observer/adapters. An acquired lease is safely released and a prepared component is safely released if strict telemetry fails after acquisition or preparation.

## Metrics

Metric dimensions pass a fixed name-and-value allow-list. Activation IDs, tenant IDs, service IDs, release IDs, revision IDs, trace IDs, arbitrary error text, and arbitrary guest fields are never metric labels.

The shared path records:

- lifecycle event counts and durations;
- total activation latency and the three terminal outcome classes;
- queue wait, queue depth, pool capacity, available/active/quarantined cells, cancellation, release, and quarantine behavior;
- execution duration, explicit guest outcome, interruption kind, and cleanup disposition;
- granted and consumed fuel, memory, wall time, child calls, outbound calls, state/blob I/O, log bytes, and effects;
- budget exhaustion for every granted dimension;
- current route generation;
- prepared-cache entries, resident source bytes, hit, miss, and eviction counts; and
- telemetry queue, accepted/exported, drop, and sink-failure state.

Prepared-cache hit/miss counters cover `prepare` reuse lookups. Runtime retrieval of an already-prepared handle does not count as a preparation hit. Evictions count only capacity/byte-pressure removal, not explicit release.

## Privacy and redaction

Guest log content is deny-by-default. Message bodies are emitted as `[REDACTED]` unless bounded body export is explicitly enabled. Guest field values are redacted unless the exact field name is explicitly allow-listed. Even explicit export rejects credential-shaped data, JSON/form-style secret assignments, authorization material, cookies, private keys, and stack/backtrace text. Raw activation input/output payloads and guest backtraces are never copied into telemetry.

The finite Phase 0 CLI applies the same conservative treatment to its captured-log rendering: field values and non-empty message bodies are redacted. The invocation output itself remains the explicit response surface and is not republished as telemetry.

## Backpressure and failure isolation

Activation code uses only `try_send`; it never waits for exporter capacity. One record may be in the sink and at most `queue_capacity` records may wait in the node queue. Queue-full, queue-closed, invalid-record, and sink-failure counters are retained separately. A deliberately blocked-sink test proves the queue remains bounded and that strict mode returns `ResourceExhausted` instead of silently swallowing the configured failure.

`flush` and graceful shutdown are operator/test boundaries. They are not used from the invocation hot path. The finite executable flushes and shuts down the node exporter during process cleanup; abnormal construction paths abort the one node task.

## Live inventory

`StandaloneInventoryReporter` requests only bounded data:

- the configured cell classes from `CellPool::observations`;
- one retained `RouteGenerationSource`;
- constant-time prepared-cache aggregates and at most a requested descriptor sample;
- live queue/cache/telemetry pressure;
- live readiness and health; and
- fixed and activation-scoped topology through `bounded_topology(maximum_entries)`.

The reporter asks the fixed source for at most the configured maximum, then asks the dynamic source only for the remaining budget. A dynamic source therefore cannot build an unbounded topology and rely on truncation afterward.

The Phase 0 fixed topology reports only measurable node-owned resources: configured/current Tokio workers, the one telemetry exporter task, and the fixed generic cell pool. Activation-scoped Wasmtime stores, host states, component instances, temporary buffers, cancellation probes, and invocations come from live backend counters. Worker rows are not duplicated. Synthetic dormant-service zero rows and an unobservable hard-coded epoch-helper row are not emitted.

Health becomes unhealthy when the exporter is closed or all execution cells are quarantined, and degraded when telemetry drops/sink failures or partial quarantine are observed. Pressure values are normalized to 0–1000 and derive from current pool queue occupancy, prepared-cache entry/byte occupancy, and telemetry queue occupancy. Phase 0 has no process-wide resident-memory sampler, so its reported memory pressure is explicitly the bounded node-owned prepared-cache byte pressure rather than a fabricated zero.

## Dormant-release scaling evidence

`LocalInvariantProbe::idle_scaling` requires an `IdleScalingDriver`. It captures inventory and the actual registered-release count, registers the requested dormant releases, verifies the observed count changed by that amount, captures inventory again, and reports whether process, thread, task, timer, socket, connection, exporter, cell, service-resident-resource, and resident-cache counts stayed unchanged. The validation includes a 10,000-record release-catalog coupled experiment plus a negative control that introduces one service-resident task per release and proves the probe detects the leak. Without a driver it returns an error; it never copies a caller-supplied count into a purported observation.

## Validation

`.github/workflows/issue-13-validation.yml` runs against the actual pull-request head with read-only repository permissions. It does not check out a hard-coded branch, mutate the workspace, commit generated changes, or push. The gate runs formatting, workspace check, Clippy with warnings denied, affected-package tests, generated contract/component validation, the real ignored `latentd` executable end-to-end test, and a separate Rust 1.94.1 MSRV check.
