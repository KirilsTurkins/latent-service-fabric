# Shared telemetry and standalone node inventory

LSF observability is a node resource, not a service resource. A standalone node owns one bounded telemetry queue, one exporter task, and one or more node-level sinks. Registering or leaving a service dormant does not create an exporter, timer, thread, socket, connection, or telemetry queue for that service.

## Telemetry data path

`latent-telemetry` separates the invocation hot path from export:

1. Activation, scheduler, execution, and cleanup boundaries call the synchronous `ActivationObserver` hooks.
2. `SharedActivationObserver` creates bounded records and submits them through `TelemetryHandle::try_emit_*`.
3. Submission uses `tokio::sync::mpsc::Sender::try_send`; it never waits for queue space.
4. One node-owned `TelemetryRuntime` task drains the bounded queue and calls the configured `TelemetrySink`.

The default queue holds 1,024 records. Record text, trace identifiers, attribute counts, names, and values are bounded before enqueue. `StructuredLocalSink`, intended for development and tests, is independently bounded by both retained entry count and approximate retained bytes and evicts the oldest records first.

A blocked exporter can occupy only the single in-flight record plus the bounded queue. New records are dropped when the queue is full. A closed queue, invalid record, queue overflow, and sink failure are counted separately in `TelemetryPipelineSnapshot`; `TelemetryHandle::operational_metrics` exposes the same values as bounded metrics. Sink errors are counted and the worker continues. Observer and exporter failures are not returned through activation results.

`flush` and graceful shutdown are operator/test operations and may wait for the exporter. Invocation paths do not call them. An owner that must terminate a permanently blocked exporter can use `TelemetryRuntime::abort`.

## Lifecycle and outcome model

The shared observer emits correlated logs, spans, counters, and histograms for:

- receipt, resolution, admission, queueing, materialization, execution, cancellation, failure, completion, and cleanup;
- queue wait and total activation latency;
- budget grants and finalized consumption for fuel, memory, wall time, calls, I/O bytes, log bytes, and effects;
- successful guest returns, declared guest/domain errors, and platform failures as distinct outcome values;
- cancellation, deadline, resource exhaustion, guest trap, and stable platform error codes.

Until issue #36 replaces the current two-variant Rust `ActivationOutcome`, declared guest/domain errors are recognized through a bounded, explicitly configured set of output media types. The Phase 0 composition registers its domain-error media type. This compatibility adapter does not infer domain errors from error text and does not collapse them into platform failures.

Completion logs and the root activation span contain finalized consumption. Metrics deliberately omit activation, tenant, service, release, and revision identifiers to avoid unbounded labels.

## Guest log correlation and privacy

The Wasmtime host already buffers structured guest logs per invocation and publishes them to one bounded node sink. `Phase0NodeObservability` forwards those records into the shared pipeline before activation completion removes correlation state. Each guest log receives:

- activation, tenant, and service context;
- resolved release and revision context (the direct Phase 0 adapter uses the real release and the fixed revision name `phase0-direct`);
- current route generation;
- trace context and normalized severity.

Metric attributes use a fixed allow-list. Logs and spans retain bounded correlation fields, but caller baggage, principal claims, unrestricted envelope metadata, raw input/output payloads, request/response bodies, and guest backtraces are not copied. Attribute names associated with credentials, authorization, cookies, passwords, tokens, API keys, private keys, or sessions are replaced with `[REDACTED]`. Log bodies containing common credential markers such as authorization headers, bearer tokens, passwords, secrets, API keys, private keys, cookies, or sessions are replaced wholesale with `[REDACTED]`. Because arbitrary secret values cannot be identified without a schema, guest code must still treat the structured field boundary as the safe place for sensitive values and avoid embedding opaque credentials in prose.

## Inventory collection

`StandaloneInventoryReporter` assembles one bounded snapshot from fixed, constant-time node sources:

- `CellPool::observations` for the configured cell classes only (at most the five enum classes);
- `RouteGenerationSource` for the current generation, without enumerating services or routes;
- `CacheInventorySource` for a fixed-size aggregate and an optional bounded descriptor sample;
- `MemoryPressureSource` and `NodeHealthSource`;
- a configuration-time fixed topology plus an optional constant-time dynamic topology source, with at most 64 entries after defensive normalization.

The inventory reports capacity, availability, queue depth, cache occupancy/limits/behavior counters, memory/queue/cache/telemetry pressure, readiness and health, and fixed topology. Cache sources must honor the requested descriptor limit without walking a full release catalog; the reporter defensively truncates a misbehaving source as well.

Topology entries distinguish:

- `NodeFixed`: runtime workers, the telemetry exporter task, Wasmtime's epoch helper, and generic execution hosts;
- `ActivationScoped`: active invocations, stores, host state, component instances, cancellation probes, and temporary buffers sampled from the backend and expected to return to zero while idle;
- `ServiceResident`: a category reserved for resources tied to a deployed service. The standalone composition reports zero dormant-service processes, threads, and sockets.

`NodeInventory::operator_summary` is the bounded CLI rendering surface. `InventoryReporter` is the direct readiness/health seam for issue #37. `LocalInvariantProbe` in `latent-testkit` exposes the same snapshot and structured local metrics without accessing a deployment or release catalog.

## Exporter integration

A production exporter implements `TelemetrySink` once at the node composition root and is passed to `TelemetryRuntime::spawn`. OTLP, a local collector socket, or a file-backed development adapter can be implemented without changing activation, scheduler, or execution code. Export adapters should apply their own bounded timeouts and bounded retry policy; they must not create per-service workers or queues. The core pipeline intentionally contains no unbounded retry buffer or durable audit store.
