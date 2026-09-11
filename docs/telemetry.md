# Shared telemetry and node inventory

`latent-telemetry` implements one bounded export pipeline per node, a structured
local sink, and activation observation. `latent-node` supplies lifecycle hooks
and bounded inventory collection. These Rust APIs are available to the standalone
node composition and management adapters; they do not create a public listener.

## Ownership and lifecycle observations

`LocalActivationServices::observer` attaches an `ActivationObserver` directly to
the existing activation owner. The observer receives payload-free
`ActivationObservationContext` and `ActivationObservation` records. It does not
wrap the manager, allocate another cancellation owner, or finalize another ledger.

Receipt follows successful identity/journal reservation and is observed before
the handle is returned. Phase observations follow committed journal transitions.
Resolution supplies the pinned release, revision, and route generation. Admission
supplies the actual granted budget. Queue-wait and phase durations come from the
manager's monotonic elapsed time, including interruption while queued.

Terminal observation follows resource disposition, budget finalization, selection
of the cancellation/completion winner, and terminal journal publication. It
contains the exact resulting terminal state and consumption. Guest success,
declared guest error, and platform failure have distinct classifications. Handle
abandonment and contained poll/destructor panics use that same terminal path.
Cleanup observations distinguish confirmed release/quarantine, reclamation before
execution, abandonment, failure, and cases without an acquired cell.
Standalone transport disconnects keep that same observation lifetime while the
bounded cleanup supervisor drives the original owner. A raw disconnect emits no
accepted explicit-cancellation observation; its terminal result does not by
itself prove that the cell was safely reused.

Each lifecycle stage produces correlated logs/events. Terminal observation emits
one complete activation span using the supplied span identity; intermediate
stages do not create additional spans with that same ID.

Callbacks run outside journal and cancellation locks. Observer panics cannot
replace a committed activation result. The built-in observer uses a short mutex
critical section for bounded correlation bookkeeping; it does no exporter work
under that lock. It never waits for exporter capacity.

Correlation is keyed by a manager/sequence token, independently of the caller's
activation ID. Overlapping incarnations can coexist after journal eviction or
across managers. Completing an older token cannot remove a newer one. Guest logs
carry an activation ID: when that ID maps to multiple active tokens, the observer
drops the ambiguous log instead of choosing a tenant or invocation.

## Bounds and redaction

`SharedActivationObserverConfig` bounds active correlation count, each identity
string, aggregate context bytes, borrowed guest-log input, and exported guest
fields/body. Borrowed input is validated before retention or redaction copies.
An entry-count cap also bounds boxed correlation records and their token/ID
indexes. Capacity pressure rejects additional correlation entries and counts the
drop; it never evicts a live entry. Terminal processing removes its matching token
even when export submission fails.
Retained allowlist vector/string capacities are validated at construction.
Configuration arithmetic includes context strings, the secondary identifier
index, and conservative bookkeeping. Context replacement does not reuse spare
capacity from earlier field values.

Correlation includes bounded activation/root/parent IDs, tenant, service,
contract/function, trace ID/span ID/flags, and pinned release/revision/generation.
It carries no invocation payload, principal subject/claims, caller metadata,
baggage, error payload/message, or cancellation reason. Exported identifiers may
be truncated to the configured attribute bound; internal matching uses complete
validated identifiers and tokens.

Guest message bodies are `[REDACTED]` by default. Unknown guest field names are
dropped entirely, including their names. Only exact names in
`allowed_guest_field_names` may export bounded values, under a `guest.` prefix.
The field-name bound includes that prefix. Case-insensitive `latent.` names and
credential-shaped field names are forbidden in the allowlist; recognized
credential/backtrace-shaped values remain redacted. Trusted correlation comes
only from the registered lifecycle context. Opting into body or field export
requires selecting appropriate content; substring filtering is not a general
secret classifier.

The Wasmtime structured-log bridge submits each accepted host log immediately.
It does not replay a captured-log snapshot after execution. Default queue drops
remain successful host-log acceptance, with normal budget charging and visible
telemetry drop counters. Explicit `fail_on_drop` is a test option and may return
host-log unavailability. The existing bounded runtime capture remains a local
diagnostic facility, separate from redacted export.

Metric dimensions come from fixed enumerations: lifecycle stage, outcome class,
platform error code, resource, severity, cancellation/disposition result, and
configured cell class. Activation/tenant/service/release identifiers and guest
values are never metric labels. Metrics include lifecycle/outcome counts,
monotonic latency and queue wait, granted/final consumption, observed resource
limits reached, cancellation and cleanup. Floating-point metrics are approximate;
terminal logs preserve exact integer consumption. Reaching a grant is separate
from the terminal resource-exhaustion error classification.

## Export pipeline and local sink

`TelemetryRuntime::spawn(config, sink)` returns a `TelemetryHandle` and its worker
owner. Submit metrics/logs/spans through `try_emit_*`; producers never await the
sink. The default queue holds at most 1024 records, each charged at most 64 KiB.
Charges include owned string capacities and conservative record/map bookkeeping.
Channel slots and the single currently exporting record are separately bounded.
The local sink defaults to 4096 records and 8 MiB, evicting its oldest records
within both bounds. Configure observer attribute limits consistently with the
pipeline's record and attribute limits.

Snapshots expose accepted/exported records, queue depth, full/closed/invalid drops,
sink failures/timeouts, and flush/shutdown failures. Observer snapshots separately
expose retained correlations and rejected or failed observation attempts.
Sink failures do not change the production activation outcome.

Export, flush, and shutdown have explicit deadlines. Exporters must cooperate with
async polling: a deadline cannot interrupt blocking code inside a callback.
`flush()` is a barrier over preceding export attempts, including failed/timed-out
attempts; inspect the counters to determine delivery. Dropping the runtime owner
closes producers and aborts the worker. Queued/export futures are reclaimed when
the runtime polls that abort. No exporter task belongs to a dormant service.

An external exporter implements `TelemetrySink` and is installed once at node
composition. It should use bounded transport buffers and cooperate with its
deadline. OTLP/network exporter implementations remain an integration choice;
the maintained local sink supports tests and development without infrastructure.

## Inventory

`StandaloneInventoryReporter::new(config, node, sources)` provides synchronous
`snapshot_now()` and the `InventoryReporter::snapshot()` port. Collection reads
the configured cell classes, scheduler counters, local quota totals, route
generation, bounded cache/topology sources, and load observations. It creates no
worker and never enumerates a release, deployment, tenant, or activation catalog.
`NodeInventory::metric_points()` produces a bounded set of fixed-dimension metrics.

The result includes capacity/availability/active/quarantined cells, queue bounds
and wait totals, route generation, cache costs, quotas, load age/availability,
health/readiness, and topology. Cache source/metadata/compiled-image and in-flight
preparation costs remain separate from process RSS and activation pins.
`retained_bytes` charges the returned snapshot, including spare capacity and
collection bookkeeping, rather than source-owned state.

Topology explicitly distinguishes `NodeFixed`, `ActivationScoped`, and
`ServiceResident` resources. Configured counts and observed active counts are
separate: `None` means unmeasured, and source availability/completeness remain
explicit. Cache occupancy cannot establish process memory pressure. Busy cells
can remain ready; unavailable/stale load or no usable cells makes the node
unready. A scheduler that has stopped accepting work is unready even while its
configured capacity remains visible; deliberate shutdown can remain healthy.
Optional cache/topology failures degrade diagnostics without inventing
observations or changing guest execution.

The standalone `wasmtime-compiler` topology row is a `NodeFixed` thread resource.
Its configured count comes from the compiler pool's maximum workers, and its
active count is the pool's observed live workers, including idle workers. Job
counts and joined workers do not stand in for live threads. The row uses the
existing bounded topology writer; a selection that omits rows remains incomplete.

## Validation

```bash
cargo test -p latent-telemetry --locked
cargo test -p latent-node --locked
tools/validate_contracts.sh
```

Tiny fixtures cover redaction, distinct outcomes, pinned correlation, monotonic
timing, overlapping tokens, bounded queues/sinks, failure isolation, and inventory
bounds. Lifecycle and real-component integrations exercise observation through
cleanup. The separate [Phase 1 completion report](phase-1-completion.md)
records the completed scaling/reclamation gate; the
[extension report](phase-1-extension-completion.md) records later performance
results and their limits.
