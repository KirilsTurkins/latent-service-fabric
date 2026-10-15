# latent-telemetry

Bounded logs, traces, metrics and activation observations on one node-owned exporter. `SharedActivationObserver` tracks payload-free lifecycle correlation and redacts accepted fields; producers submit without awaiting the sink. Custom metrics and canary windows have separately bounded identity/cardinality rules.

Telemetry is diagnostic and may drop records under its explicit policy. It is not the durable administrative/security audit journal.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Metric/log/span records and sink/observer traits. |
| [src/observer.rs](src/observer.rs) | Bounded correlation, redaction and nonblocking exporter submission. |
| [src/pipeline.rs](src/pipeline.rs) | Finite queue, shared worker, drop/failure counters, flush and shutdown. |
| [src/local.rs](src/local.rs) | Bounded StructuredLocalSink preserving already accepted records. |
| [src/custom.rs](src/custom.rs) | Explicit application metric policy, series/label bounds and original queue charges. |
| [src/phase2_canary.rs](src/phase2_canary.rs) | Control-registered cohort capture and sealed observation windows. |
| [src/observation.rs](src/observation.rs) | Payload-free activation lifecycle observations. |

## Execution and ownership

1. Construct a shared exporter/sink and observer with finite queue, memory and cardinality limits.
2. Lifecycle owners emit bounded observations; the observer redacts before nonblocking submission.
3. The worker exports with explicit sink timeout/failure/drop accounting while retaining actual queued/active record charges.
4. Flush/shutdown waits for real owned work within the selected bound. Canary promotion uses a sealed completed window, not a freely constructed report.

## Integration boundaries

Sinks do not automatically redact arbitrary raw payloads; producers and the observer own that boundary. Metric labels cannot create unbounded tenant series. A successful telemetry export is not durable audit acknowledgement, and a missing trace is not proof an invocation never ran.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-wire](../latent-wire/README.md), [latent-node](../latent-node/README.md), [latent-control-store](../latent-control-store/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-telemetry.lib.latent-telemetry
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`aggregates_preserve_counter_sign_gauge_order_and_exact_histogram_buckets`](src/custom/registry/tests.rs)
- [`invalid_observations_and_label_injection_allocate_no_series_or_queue_records`](src/custom/registry/tests.rs)
- [`series_caps_separate_tenants_and_fixed_rate_windows_refund_rejections`](src/custom/registry/tests.rs)
- [`config_failure_does_not_consume_installation_but_retired_owners_cannot_be_replaced`](src/custom/registry/tests.rs)

## Related documentation

- [Bounded guest custom metrics](../../docs/runtime/custom-metrics.md)
- [Capability audit and inspection](../../docs/runtime/capability-audit.md)
- [Data-plane architecture](../../docs/architecture/data-plane.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
