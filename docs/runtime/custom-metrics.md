# Bounded guest custom metrics

The configured `MetricProvider` implements
`latent:telemetry/custom@0.1.0` on the existing shared telemetry pipeline. Every
`emit-metric` requires the exact import, installed provider identity, current
publication and policy, and an operation grant with resource kind `telemetry`
and an allowed metric name. Guest strings never select a provider or supply
trusted source identity. An uninstalled import fails preparation. The WIT and
host ABI version are unchanged.

## Composition and identity

An embedding supplies `MetricProvider::install(&broker, telemetry_handle, epoch,
config, activation_limits)` and calls
`ActivationCapabilityRuntime::install_metrics` with the returned `Arc`. Its
`reference()` supplies the `custom-metrics-v1` profile, configuration digest and
epoch for durable bindings and exact plan compilation. Standalone provider
configuration is tracked by [#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226).

`CustomMetricsConfig` declares exact tenant policies, metric names, kinds, units,
label keys and permitted values. It has no wildcard labels. Names start with an
ASCII letter and contain only letters, digits, `_` and `.`. Case-insensitive
`latent`, `otel` and `host` prefixes are reserved. Units use nonempty ASCII
letters, digits or `_.-/`. Names are at most 64 bytes, units 16, label keys 32,
and label values 64. Duplicate keys or values are rejected. Values must be
explicitly configured nonempty ASCII graphic strings; choose nonsecret data.
Optional labels are canonicalized in descriptor order, independently of guest
ordering. Omission is a distinct series.

Every exported name has the host prefix `latent.application.`. Attributes
`latent.tenant`, `latent.service` and `latent.revision` come from the sealed
activation plan. Allowed application labels appear under `guest.`. Public
activation IDs, principal claims and arbitrary caller metadata are not labels.
Two independently authorized publications containing identical component bytes
retain independent tenant series, permissions and activation allowances.

One registry can be installed during a pipeline lifetime. It holds bounded node
configuration and a preallocated fixed-capacity series table; there is no
registry, exporter, task, timer or connection per dormant service. Retirement
stops new observations without deleting accepted queue owners. Reconfiguration
requires a new node/pipeline composition. Failure after installation during
composition also requires a new pipeline; it cannot silently replace a live
registry. Compiled components may retain the shared provider owner, but never an
activation's mutable metric state.

## Aggregation contract

All values must be finite. Same-name descriptors across tenant policies must use
the same kind, unit and histogram bounds. No implicit type or unit conversion is
performed.

| Kind | Accepted value and exported aggregation |
| --- | --- |
| Counter | Nonnegative delta; running sum and observation count. |
| Up-down counter | Signed delta; running sum and observation count. |
| Gauge | Last accepted sample, ordered by the registry's monotonic acceptance sequence, independent of wall-clock ordering. |
| Histogram | Observation plus running count, sum and fixed disjoint bucket counts. Each finite bound is inclusive; the final bucket covers values above the last bound. |

Histograms have at most 16 finite, strictly increasing operator-supplied bounds.
Guests cannot create bucket maps. An empty bound list has only the final bucket.
Count/sequence overflow and nonfinite sum results reject the observation without
changing the aggregate. Floating-point sums are approximate. Aggregation covers
accepted observations even if their subsequent export fails. It is process-local
diagnostic state and is not recovered after restart.

## Admission, bounds and ownership

| Scope | Default and hard bound |
| --- | --- |
| Configuration | At most 8 tenants, 32 descriptors per tenant, 128 total, 256 KiB charged metadata; actual vector/string capacities are checked. |
| Label cardinality | At most 8 keys and 16 exact values per key. Combined supplied key/value bytes default to 1,024; hard maximum 4,096. |
| Active series | Node default 512, hard maximum 1,024; tenant default 64, bounded by the node ceiling. No eviction silently resets an active aggregate. |
| Observation rate | Node default 4,096 per second, hard maximum 16,384; tenant default 1,024, bounded by the node ceiling. One shared monotonic one-second window, with no timer. Clock rollback grants no fresh window. |
| Queued/exporting custom bytes | Node default 4 MiB, hard maximum 32 MiB; tenant default 512 KiB, bounded by the node ceiling. Each observation reserves a conservative 32 KiB before allocation. |
| Activation | Default 128 observations, 16 distinct series and 1 MiB cumulative record allowance; hard maxima 1,024 observations, 32 series and 4 MiB. All apply together: the default byte allowance permits at most 32 accepted records. |
| Shared exporter | Existing channel capacity and one exporting future; custom metrics share capacity with lifecycle logs, spans and runtime metrics. The local sink has its own bounded retention. |

Validation and exact policy checks precede record copying. Pending activation
reservations cover observations, distinct series and record bytes. Required
audit admission completes before capture. Registry admission uses a nonblocking
lock and reserves both channel capacity and node/tenant bytes before allocating
the record or updating aggregation. Input strings are replaced with a compact
validated selection before asynchronous audit waits. That selection is bound to
the exact registry and trusted source; it grants no execution permission.

Dropping unstarted work or rejecting capture refunds pending activation quota.
Accepted observations remain spent even if export fails. The original queue
charge remains owned through actual export completion, timeout or abort cleanup;
returning to the guest does not refund it. The local sink independently charges
its retained records. Broker result ownership survives guest lowering until
Store destruction. Session metadata includes its bounded activation series table.

Every call prepays CPU fuel `100 + bounded retained input bytes` through the
original activation ledger, plus normal broker call/input metadata reservations.
Fuel is accounting work, not a latency guarantee. No outbound-request, log, blob,
child-call, state or effect allowance is consumed. Cancellation and deadlines are
checked before dispatch and before returning control to the guest.

## Acceptance, failure and export

`ok(true)` means admission to the bounded capture queue. This profile never uses
`ok(false)`; it returns `invalid-name` for invalid observations or configuration
mismatches, `budget-exhausted` for quotas, busy/full capacity or arithmetic
overflow, and `unavailable` for closed/retired owners or authorization failure.
The frozen WIT error names do not imply that only the name field is validated.

Capture acceptance is not exporter acknowledgement, persistence or durable audit.
`MetricProvider::snapshot()` counts guest attempts, captures and typed failures.
`CustomMetricRegistry::snapshot()` reports active series, outstanding bytes,
capture outcomes and retirement using fixed numeric fields. Validation done by a
broker before registry submission appears in the provider's counters. Pipeline
snapshots separately report actual exports, sink failures, timeouts and panics.
Required capability audit records an admitted operation and `HostCompleted` or
`Rejected`; those outcomes describe capture, not monitoring delivery.

The shared `TelemetrySink::emit_custom_metric` receives an immutable
`CustomMetricPoint` with the point, acceptance sequence and aggregation.
`StructuredLocalSink` supports it. External sinks must implement that method;
the default explicitly returns unavailable, which increments sink failures.
There is no selected OTLP adapter in this repository. Integrations use this
existing shared exporter port and must bound their own buffers and cooperate
with asynchronous deadlines. A blocked synchronous exporter cannot be forcibly
interrupted by a timer. `flush()` waits for preceding attempts, including failed
attempts; inspect counters rather than inferring delivery from its success.

## Verification

```sh
cargo test -p latent-telemetry --lib --locked
cargo test -p latent-wasmtime --test metrics --locked
cargo test -p latent-capabilities --lib --locked
```

Real canonical ABI guests cover all four kinds, nonfinite values, incompatible
kind/unit reuse, duplicate/reserved labels, cardinality and activation limits,
closed sinks, missing authority, retirement and required audit. Identical Wasm
publications execute for two tenants on the same backend/cell with independent
aggregates. Ownership cases cover pending refunds, queue failures, fuel,
cancellation and held results after session closure. Shared exporter cases cover
overflow, slow/panicking/unsupported sinks, timeout and abort reclamation. These
bounded tests require no large load benchmark.
