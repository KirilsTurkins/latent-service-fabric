# Generic Wasmtime execution

`WasmtimeComponentEngineFactory` and `WasmtimeBackend` implement the Phase 1
Component Model execution port. They prepare a locally trusted `CapsuleArtifact`
and invoke the requested exported contract and function through
`ExecutionBackend`. The caller supplies a pinned prepared component, activation
envelope, granted budget, cell, and activation-owned cancellation view.

This Rust API is a runtime building block used by the
[activation lifecycle manager](../activation-lifecycle.md). Public invocation
services and the standalone node remain separate Phase 1 work.
The `Phase0WasmtimeEngineFactory` compatibility facade preserves the
retained echo demonstration and its original text/domain-error wire format.

## Preparation and dispatch

Preparation verifies component bytes and digest association, manifest execution
requirements, declared imports/exports, and supported exported signatures.
Stateless components may declare single-threaded or reentrant execution;
cooperative threading and persistent state models are not admitted.
Contract and function lookup use the component's actual exported interfaces;
the generic dispatcher contains no echo function or containment-control-string
selection. Components with no imports are supported.

The generic payload media type is
`application/vnd.latent.wit-values.v1+json`. Parameters and results use positional
JSON arrays with the canonical scalar, record, tuple, list, option, result,
variant, enum, and flags mapping defined in the
[value protocol](../protocol/wit-values.md). A sole top-level `result.err`
becomes `GuestOutcome::DeclaredError` with code `declared-error`, a fixed message,
and the complete canonical result-array payload. Nested results remain ordinary
application values. Neither success nor declared failure is inferred from a
service-specific string.

Missing requested contracts/functions, invalid media, malformed JSON, and
incorrect value shapes fail before store construction. Structural and value
budgets bound input decoding, output encoding, nesting, collection sizes, and
type traversal. Unsupported Component Model features fail explicitly; the
protocol documents the supported subset. Preparation rejects unavailable
imports and manifest/component disagreement as `incompatible-contract`.

An output encoding limit can be reached after guest execution has consumed
resources. That failure returns `GuestOutcome::Trapped` with trap code
`result-limit-exceeded` and the measured `BudgetConsumption`, so activation
accounting retains the work already performed. Cleanup still completes before
the backend returns its reuse proof.

## Activation ownership and containment

Every invocation creates a fresh store, aggregate memory limiter, component
instance, activation context, import state, log accounting, and cancellation probe.
An activation cannot retain guest globals or linear memory for a later cell
occupant. The effective linear-memory allowance is the minimum of the node,
cell, and granted activation limits, accounted across the store's memories.

The engine enables fuel and epoch interruption. Epoch checkpoints observe the
live cancellation probe and the original monotonic admission deadline when
the cancellation view supplies it; legacy callers derive a monotonic deadline
once from the envelope's Unix deadline. Guest code
does not need to cooperate by making a host call. Guest traps, fuel exhaustion,
memory denial, cancellation, and deadline expiry are contained to the activation.
Diagnostics are bounded and do not expose raw guest payloads or engine context
chains. The retained [containment contract](../development/activation-containment.md)
describes stop-cause precedence and cell disposition.

Dynamic calls complete their canonical ABI post-return before reporting a
successful result. A post-return failure is an execution failure. The backend
drops the instance, store, host state, temporary values, and live cancellation
probe before returning `ExecutionCleanup::Reusable`. Callers must honor the
explicit cleanup proof; an outcome by itself does not authorize cell reuse.

No WASI filesystem, environment, network, process, or other ambient authority
is installed. The supported host imports are activation context, structured
logging, and monotonic/wall clocks. Their disclosure policy, shared live budget,
clock injection, and log acceptance contract are documented in
[activation capabilities](capabilities.md).

## Node policy and shared preparation

`WasmtimeConfig` carries explicit component, memory, fuel, stack, cache, logging,
epoch, instance-allocation, context disclosure, and value-codec limits. Async Component Model calls,
fuel, and epoch interruption are required containment mechanisms. The configured
epoch interval multiplied by deadline ticks must be between one millisecond
and one second. The factory validates policy before creating an engine.
The optional positive `fuel_async_yield_interval` makes async guest execution
yield after a configured amount of fuel. Its default is disabled; enabling it
does not replenish the activation's allowance and participates in preparation
compatibility. Fuel exhaustion and epoch interruption remain enforced.
The Phase 0 facade retains its stricter 80 KiB canonical-transfer allowance;
its effective allowance is also included in preparation compatibility.
`preparation_key` binds the release to the Wasmtime
version, engine configuration, host target, and CPU compatibility identity;
incompatible keys cannot reuse preparation state.

Prepared entries retain compiled components and pre-instantiation/export
metadata, never running stores or component instances. The internal preparation
identity also binds a deterministic, engine-version-scoped fingerprint of
bounded artifact metadata, including the declared budget and contracts: unchanged component bytes cannot reuse a different metadata
policy accidentally. Backends created by one factory share this cache.

The cache defaults to eight entries, 64 MiB of source bytes, 8 MiB of bounded
metadata accounting, and 128 MiB of compiled image address ranges. These are separate
admission dimensions; compiled-image accounting is not a measurement of all
compiler heap allocations or process RSS. Eviction and `release` remove cache
ownership. An executing activation may retain its bounded runtime pin until
cleanup, so resident cache counters exclude those active evicted pins.

Activation orchestration obtains the engine key through
`ExecutionBackend::preparation_key` and calls `prepare_for_use`. Its affine
`PreparedUse` retains the exact immutable runtime and one shared instance
reservation from materialization through `invoke_prepared_contained`. Invocation
consumes this owner without looking in the cache again, so eviction or explicit
legacy `release` cannot invalidate an already prepared use. Dropping an unused
owner releases its pin synchronously. The backend rejects tokens from another
factory or descriptors that differ from the token's original descriptor.

`active_instance_reservations` reports both materializing prepared uses and
running invocations against `maximum_instance_reservations`; the same reservation
is transferred into execution. Resident cache limits remain separate. Evicted
runtime pins are bounded by this shared reservation count and each runtime's
validated source, metadata, and compiled-image ceilings. These counters do not
claim to measure total process memory. Legacy `prepare` still returns only a
descriptor, which can become absent after eviction; legacy `release` removes
cache ownership and is not activation cleanup.

Each invocation owns a store guard that observes remaining fuel and confirmed
peak linear memory into the activation's existing accounting handle before
destroying the store. It also runs when the invocation future is dropped or
unwinds. Normal completion advances the same fuel watermark first, so the final
drop observation cannot charge the same work twice. The activation manager must
drop the backend future before finalizing its budget and disposing of its cell;
an abandoned future does not itself produce a reusable-cell proof.

At most two preparations compile concurrently by default. Duplicate in-flight
work or a full compilation allowance returns retryable `unavailable` without
an internal wait queue. In-flight source and metadata bytes are reported
separately. A shared instance gate defaults to 64 active component instances
across the factory's backends, and each store also has explicit instance,
memory, table, and table-element limits. Pooling exposes its component/core
instance and allocation bounds in the same policy. All of these resources are
node-owned; preparation does not allocate a service-specific cell, listener,
or execution worker.

The factory owns the engine and one weak-engine epoch ticker. Any additional
Wasmtime compilation/runtime helpers belong to that bounded node runtime, not
to a registered service. Reusing the factory is part of this topology: creating
a separate factory for every service would violate the intended ownership
model. The focused Linux fixture verifies that preparing four dormant metadata
variants does not increase helper-thread count after initial preparation, and
creates no stores. Runtime and cache snapshots expose bounded occupancy and live activation
resource counters for tests and node integration.

## Focused validation

`tools/validate_contracts.sh` builds the maintained Rust generic component with
`wit-bindgen`, componentizes its `wasm32-unknown-unknown` core, validates tiny WAT
adversarial components, and runs `generic_backend` alongside the retained echo,
containment, and focused [capability](capabilities.md) suites. The generic fixture exports two interfaces with the
same function name, multiple parameters, composite values, declared errors,
guest-local mutable state, and direct containment functions.

The small tests cover dispatch, value mapping, rejected requests before store
creation, preparation rejection, canonical post-return failure, fresh stores,
short non-cooperative interruption, failure recovery, and explicit cleanup.
They use five-second watchdogs and only small activation counts. Run the built
fixtures directly with:

```bash
LSF_GENERIC_COMPONENT=target/capsules/generic/generic-capsule.wasm \
LSF_GENERIC_FIXTURES=target/capsules/generic/adversarial \
LSF_ECHO_COMPONENT=target/capsules/echo/echo-capsule.wasm \
  cargo test -p latent-wasmtime --test generic_backend --locked -- \
    --ignored --nocapture --test-threads=1
```

These regressions establish the behavior they exercise and live-resource
accounting at completion. They do not replace native long-running RSS/mapping,
helper-topology, dormant-release scaling, or the complete #16 conformance
evidence. Heavy calibration, profiling, and soak gates remain explicitly
requested work described in [VALIDATION](../../VALIDATION.md).
