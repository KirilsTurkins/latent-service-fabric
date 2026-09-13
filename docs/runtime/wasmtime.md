# Generic Wasmtime execution

`WasmtimeComponentEngineFactory` and `WasmtimeBackend` implement the Phase 1
Component Model execution port. They prepare a locally trusted release through
its repository, or accept a directly supplied `CapsuleArtifact`,
and invoke the requested exported contract and function through
`ExecutionBackend`. The caller supplies a pinned prepared component, activation
envelope, granted budget, cell, and activation-owned cancellation view.

This Rust API is a runtime building block used by the
[activation lifecycle manager](../activation-lifecycle.md) and the
[standalone Linux node](../reference/standalone-node.md), which supplies the
configured invocation and management listener.
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

Native trap errors can retain compiled images through their backtraces. Normal
completion classifies and destroys these errors after dropping stores and
temporary buffers, but before dropping the final invocation runtime pin and
instance permit. `activation_resource_reclamation_micros` sums those two actual
drop intervals; the intervening classification belongs to
`outcome_classification_micros`. These timing fields preserve separate boundaries
without counting classification twice.

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

The factory also derives a bounded immutable
[runtime compatibility profile](../reference/release-compatibility.md) from
the actual engine, target and detected CPU features. Capsule requirements are
checked before preparation, and the profile participates in preparation identity.
The configurable CPU cache label cannot grant support for a hardware feature.

Prepared entries retain compiled components and pre-instantiation/export
metadata, never running stores or component instances. The internal preparation
identity also binds a deterministic, engine-version-scoped fingerprint of
bounded artifact metadata, including the declared budget and contracts: unchanged component bytes cannot reuse a different metadata
policy accidentally. Backends created by one factory share this cache.

`prepare_from_repository` selects `ArtifactRepository::preparation_source` once.
The directory implementation returns a sealed, borrowed capability: both its
identity lookup and its verified fetch use the same concrete repository owner.
An outer adapter may delegate that capability, but cannot combine its token
with another repository's fetch. Without a capability, preparation fetches the
artifact and verifies its bytes, size, release association and metadata before
reuse. A source whose metadata is ineligible for a compact stamp still owns the
fallback fetch, including when the prepared cache is disabled.

The directory source issues a fixed-size token containing its open-instance
epoch, canonical component digest and size, and the normalized metadata
fingerprint with checked byte/depth requirements. The cache key includes this
identity and the engine preparation key; a hit also compares the complete token.
Warm acquisition from the resident prepared cache performs no component I/O/hash
or full metadata traversal.
It still performs the bounded cache lookup, an ordered catalog lookup, and
clones the bounded descriptor/import list needed by the activation. A missing
catalog entry returns `NotFound`. A cache miss reserves preparation capacity,
fetches verified content through the selected source, and checks its metadata
against the token before compilation.

This is reuse of an admitted snapshot, not a live audit of files on every call.
Fresh reads and recovery retain their integrity checks. A reopened repository
has a new epoch; old cached entries cannot satisfy its acquisition. Tokens keep
only the small epoch allocation alive, not the repository or its ownership lock.
Both the catalog stamp and retained cache token have explicit byte charges;
the [catalog contract](../development/local-release-catalog.md#verified-preparation-snapshots)
defines their eligibility and verification counters.

The cache defaults to eight entries, 64 MiB of source bytes, 8 MiB of bounded
metadata accounting, and 128 MiB of compiled image address ranges. These remain
separate admission dimensions. A resident hit borrows its `&str` key, performs
an expected O(1) hash lookup with respect to entry count, and promotes the entry
by updating a fixed number of recency links. The index and recency slot share
one `Arc<str>` key allocation. A reusable slot arena grows within the configured
entry ceiling and reuses vacant slots; hits neither scan the recency order nor
allocate a new key. This describes the cache operation, not the cost of the
complete preparation or invocation path. The implementation is tracked in
[#102](https://github.com/KirilsTurkins/latent-service-fabric/issues/102).

`cache_accounting_snapshot()` on `WasmtimeBackend` and
`WasmtimeComponentEngineFactory` combines the existing resident-cache snapshot
with unique runtime accounting. Each distinct prepared runtime contributes its
cost once, regardless of how many ready, active or temporary owners share it:

| Runtime population | Ownership represented |
| --- | --- |
| `unpublished` | Constructed runtimes not admitted to the cache, including uncached Phase 0 uses. |
| `resident` | Runtimes currently owned by a resident cache entry. |
| `evicted_live` | Former residents still held by ready, active, compiler or deferred-eviction owners. This is not an active-invocation count. |
| `live` | The total of the three disjoint populations above. |

Each population reports `runtimes`, `source_bytes`, `metadata_bytes` and
`compiled_image_bytes`. Source bytes describe associated component content, not
a retained source `Vec`. Metadata is the backend's bounded accounting estimate;
image bytes are Wasmtime `Component::image_range` spans. The counters count
these charges exactly once per runtime; they do not measure allocator overhead,
compiler scratch, physical pages or process RSS. Eviction and `release` transfer
a surviving runtime from resident to evicted-live accounting. The final runtime
owner refunds its charge after its native fields are destroyed. A recompiled
runtime is a separate lifetime even when an older pin names the same release.

The backend and factory also expose `prepared_runtime_observer()`. Its cloneable observer
retains only counter state, so `snapshot()` remains usable after cache/factory
destruction without keeping runtimes or workers alive. An unavailable ledger is
reported as `None`, not as zero usage. Destroying the cache removes residency;
surviving pins remain charged until their actual final drop.

Activation orchestration obtains the engine key through
`ExecutionBackend::preparation_key` and calls `prepare_ready_from_repository`
before requesting an execution cell. `PreparedReadiness` pins immutable code and
all manifest imports without an active-instance permit or Store. After assignment,
`materialize_ready` acquires one shared instance reservation and transfers that
same code pin into `PreparedActivation`. Its affine `PreparedUse` retains the
exact runtime and instance reservation through `invoke_prepared_contained`. Invocation
consumes this owner without looking in the cache again, so eviction or explicit
legacy `release` cannot invalidate an already prepared use. Dropping an unused
owner releases its pin synchronously. The backend rejects tokens from another
factory or descriptors that differ from the token's original descriptor.
Direct `prepare_for_use` callers retain the checked owned-artifact path.

`active_instance_reservations` reports both materializing prepared uses and
running invocations against `maximum_instance_reservations`; the same reservation
is transferred into execution. Resident cache limits remain separate. Evicted
runtime pins held by active uses are bounded by this shared reservation count and
each runtime's validated source, metadata, and compiled-image ceilings. Pins
waiting for a cell instead obey the separate ready count, metadata and image
allowances described below. These counters do not
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

Generic readiness uses fixed factory-owned compiler workers. The total distinct
job bound `maximum_concurrent_preparations` includes assigned and queued jobs.
`compiler_workers` defaults to the smaller of two and that bound, with a hard
worker limit of eight; remaining job slots form the queue. The standalone node
defaults to one total job and one compiler worker. Authenticated same-key requests
join one job, within separate global and per-key waiter bounds. Warm cache hits
bypass a saturated compiler queue while still obeying ready-owner limits.

The owned directory source selects one concrete repository for identity, bounds
and blocking reads, including stamp-ineligible reads. It enforces reserved
component and encoded metadata/manifest limits before growing input buffers.
Its repository/root lock remains owned until the actual job finishes; resident
cache entries and ready pins do not retain it. External repositories without
this source use their normal awaited fetch and verified owned-artifact fallback;
the runtime cannot force arbitrary external repository code to yield or bound
its private allocations.

Cancelling one waiter removes only its registration. A queued job with no live
waiters is removed without I/O. A running job with no live waiters becomes
abandoned, keeps its reservations until native compilation returns, and discards
its late result. Readiness transfers no renewed deadline or replacement budget.
Queue, worker, waiter, ready-owner and document limits are finite and separately
observed. Ready image/metadata charges conservatively account for each pin, even
when pins share code; this `ReadyGate` admission accounting is separate from the
unique runtime ledger, resident-cache limits and active-instance population.
Materializing a ready pin transfers the same unique runtime without adding a
second lifetime charge. Neither accounting nor input caps claim a total compiler
heap/RSS bound. Detailed stage/CPU observations are opt-in measurement instrumentation.

The borrowed `prepare_from_repository` and direct preparation APIs remain
compatible synchronous paths. The generic node readiness path supplies the
bounded worker behavior; the Phase 0 facade retains its original execution model.
Cache-disabled preparation remains restricted to the Phase 0 profiling facade;
the Generic factory rejects that configuration before creating its engine.
A shared instance gate defaults to 64 active component instances
across the factory's backends, and each store also has explicit instance,
memory, table, and table-element limits. Pooling exposes its component/core
instance and allocation bounds in the same policy. All of these resources are
node-owned; preparation does not allocate a service-specific cell, listener,
or execution worker.

Rust embedders must retain an external factory/runtime owner until compiler
callbacks have returned. Final pool destruction or consuming shutdown from one
of that pool's own worker callbacks cannot synchronously join the current thread.
This unsupported reentrant teardown aborts the process before invoking stop
callbacks or consuming any join handles. It supplies no graceful-cleanup proof.
The standalone node retains the factory through borrowed compiler quiescence and
then joins all workers from its shutdown owner. An isolated child test exercises
the exceptional embedding boundary without terminating the test supervisor.
Caught compiler panic payloads are disposed before job completion is recorded.
If a trusted host payload's destructor itself panics, cleanup aborts the process
without attempting recursive panic-payload destruction or reporting clean shutdown.
A separate supervised child verifies this fatal cleanup boundary.

The factory owns the engine and one weak-engine epoch ticker. Any additional
Wasmtime compilation/runtime helpers belong to that bounded node runtime, not
to a registered service. Reusing the factory is part of this topology: creating
a separate factory for every service would violate the intended ownership
model. The focused Linux fixture verifies that preparing four dormant metadata
variants does not increase helper-thread count after initial preparation, and
creates no stores. Runtime and cache snapshots expose bounded occupancy and live activation
resource counters for tests and node integration.

## Optional isolated compilation and persistent native reuse

`WasmtimeComponentEngineFactory::with_catalog_and_aot` opts into the
[trusted AOT producer and cache](trusted-aot.md) with one exact directory catalog
and `NativeAotSettings`. The standalone node exposes the same mode through
[`isolatedAot`](../reference/standalone-node.md#optional-isolated-aot-compilation).
Omitting it preserves ordinary local compilation. Configured isolated mode
rejects preparation that supplies raw artifacts or another catalog; it never
falls back to in-process `Component::new` after a cache or compiler failure.

A resident prepared hit keeps the existing fast acquisition path. A persistent
native hit follows a prepared miss and still fetches verified portable component
bytes and metadata once from the sealed source. The complete current
compatibility key selects an untrusted receipt. The configured host MAC is
verified before reading its claimed native blob, and exact bytes are verified
before the private copying loader. A missing or rejected cached entry can cause
one bounded isolated compilation while the same checked input remains owned.
Failure to persist freshly authenticated output can leave that preparation
usable without durable reuse. Source, lifecycle, policy, deadline and capacity
failures are not converted into compilation retries.

The existing fixed compiler workers own isolated jobs through child termination
and reap. Removing the last waiter signals cancellation, while removing one of
several coalesced waiters leaves their shared job running. Native deserialization
itself is synchronous and keeps its owners until it returns. Queued and prepared
tokens still require final guarded start checks; cached native provenance cannot
restore a revoked release or upgrade an older lifecycle generation.

An independent native-image permit reserves a count and the complete serialized
image size rounded to the actual host page size before loading. Defaults are
64 images, 128 MiB per image and 256 MiB total; hard ceilings are 4,096 images,
256 MiB and 1 GiB respectively. It remains with the prepared runtime through
ready and active pins, including after eviction. Native handles drop before its
final refund. The existing runtime ledger continues to report logical image
spans, while `native_aot_snapshot()` additionally reports rounded image charges,
actual loader attempts, cache observations, receipt/raw storage and producer
allowances. Loading fields are subsets, and neither accounting domain measures
process RSS or all Wasmtime allocations. No new performance or scaling result
is implied by this optional integration.

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
helper-topology, or dormant-release scaling evidence. The completed
[Phase 1 gate](../phase-1-completion.md) and
[extension report](../phase-1-extension-completion.md) record those separate
measurements and their source-specific limits. New heavy calibration, profiling,
and soak runs require explicit selection as described in
[VALIDATION](../../VALIDATION.md).
