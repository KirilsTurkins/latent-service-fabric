# Sealed activation capability broker

`latent_capabilities::broker` implements the Phase 3 activation authority and
ownership boundary. The old cloneable handle/call DTOs remain descriptive. Only
the broker's private plan, session, handle row and accepted call owners authorize
provider work. This is the implementation of [#204](https://github.com/KirilsTurkins/latent-service-fabric/issues/204),
building on [durable policies](capability-policies.md) and exact publication identity.

## Installation and session creation

One configured `ActivationCapabilityBroker` owns bounded counters, an exact
catalog owner, the configured `Arc<PolicyStore>` and an activation clock. A
trusted provider registers its capability, profile, immutable configuration
digest/epoch, resource restriction and minimum cumulative operation charges.
The affine registration's retirement or destruction denies new calls; retained
references cannot keep a retired installation authorized. Registration describes
the actual trusted provider configuration; it does not create an HTTP client,
secret store, worker pool or guest import implementation.

The privileged compiler supplies actual imported operations, deployment
restrictions, policy IDs and the provider-binding ID to `compile_plan`.
Compilation parses restrictions once and pins immutable policy rows, the exact
tenant/service/revision, route generation and publication eligibility. Plans
contain no running guest, connection, service thread or provider pool.
`CapabilityPlanSource` is the trusted bounded lookup boundary for those plans.
The coherent control snapshot, concrete provider selection and configuration
path are [#207](https://github.com/KirilsTurkins/latent-service-fabric/issues/207);
this broker adds no competing route journal or temporary configuration format.

`WasmtimeHostServices.capabilities` explicitly installs an
`Arc<ActivationCapabilityRuntime>`. A managed factory requires its exact catalog
and clock owner. Standalone composition additionally checks the exact configured policy
store; an equivalent directory path or matching generation is insufficient.
The existing standalone configuration does not yet construct this plan source;
enabling policy CRUD alone does not silently switch guest authorization modes.
Trusted embeddings with `capabilities: None` retain the existing built-in host
profile and exposure policy. Unmanaged factories reject a supplied managed broker.

Before constructing a guest Store, the runtime opens a fresh affine session
using the pinned request, verified prepared imports, current publication and
the cancellation owner's original `ActivationBudget` and live probe. Missing
ledger/probe, another tenant/catalog/publication, mismatched grant or route
generation, and duplicate sessions on the same live ledger fail closed.
The session uses the Store's computed effective deadline, including a tighter
explicit request deadline, and cannot extend the original ledger deadline.
There is no fallback ledger in broker mode. Claims, opaque import strings,
component digests and cached prepared objects cannot substitute this authority.

## Bind, dispatch and revocation

A guest handle consists of a table slot and a process-unique incarnation. It is
lookup data inside one session, not a transferable grant. IDs never wrap; an
exhausted issuer rejects new handles. A row fixes its operation, exact resource,
policy snapshot, provider installation and publication. Closing a slot twice,
guessing an ID or reusing a previous cell's handle grants no access.

Both bind and every new dispatch evaluate the intersection of actual imports,
deployment restrictions, current tenant policy, trusted principal and provider
configuration. Currentness is rechecked at the final guarded start. The fence
order is broker, provider, session, policy, catalog, publisher authority, then
the original budget ledger. Ledger methods never acquire an authority fence.
Hot paths use bounded try-lock/try-read operations and perform no policy parsing,
filesystem access or blocking control-writer acquisition. No fence crosses
provider I/O, callback execution or an await.

An unpolled call future has accepted no work and owns no call capacity. There is
no broker work queue. Revocation before guarded start prevents dispatch;
revocation afterward permits that already accepted operation to finish under its
original ownership. A provider pool must queue before dispatch and recheck at
actual start. Session closure, cancellation, deadline expiry and node retirement
close admission and expose cancellation to accepted work. They do not prove that
a remote effect did not occur or authorize replay.

## Budgets, buffers and cleanup

`CapabilityCallCost` comes from the trusted adapter's actual operation. Installed
minimum charges prevent omitted required counters. `ActivationBudget::reserve_group`
reserves all requested cumulative dimensions atomically on the original ledger;
failure changes no counter. Final admission commits the group together before
dispatch. Unaccepted reservations refund together; accepted attempted-operation
charges remain consumed. More detailed byte settlement and descendant budgets
belong to [#208](https://github.com/KirilsTurkins/latent-service-fabric/issues/208).

The affine `ProviderCall` moves into the actual worker or future. Abandoning a
waiter cannot refund a detached worker's call, handle or buffers. Owned byte
responses retain the original session and row; their bytes are zeroed before
their reservations are released. A response from a different call/session is
rejected. Errors expose a bounded code and redacted message. The trusted typed
adapter counts input before copying/encoding it and retains its call owner
until that actual input is destroyed.

In broker mode the built-in context, clock and logging adapters also pass through
this boundary. Context/clock denial traps without changing their WIT signatures.
Logging reports the existing `unavailable` result. Logging reserves exact encoded
`LogBytes` before provider admission and preserves the existing refund on known
sink rejection; it is not charged a second time by the generic adapter.

The generated typed context binding has no post-lowering callback. Heap-bearing
context results therefore conservatively retain their call/result, handle and
output reservations through canonical lowering and component post-return until
Store destruction. Repeated context reads can exhaust those configured caps
within an activation. Scalar clock/budget/deadline calls release their temporary
owners when the synchronous host call returns. This limit is explicit, rather
than treating a returned Rust DTO as proof of completed lowering.

Default global limits are 32 providers, 256 plans, 128 sessions, 2,048 handles,
256 calls, 256 result owners, 8 MiB charged metadata and 32 MiB charged buffers.
Each session permits 16 retained handles and 16 calls; input/output payloads are
each capped at 64 KiB. Configuration has finite hard ceilings. Reservations
precede table, row, payload and result allocation. Metadata charges are
conservative logical accounting, not total process RSS or allocator measurements.

Session destruction invalidates all lookup slots. Existing work/result owners
retain their charges until physical destruction. The cleanup observer contains
only counters and cannot retain an identity, plan or Store. Wasmtime reports a
cell reusable only after Store destruction and quiescent capability ownership;
otherwise it reports quarantine. Ledger finalization alone is not a cleanup
proof. Node drain/drop retires the configured broker; retirement also releases
its plan source before the policy shutdown check. External retained owners make
incomplete cleanup visible rather than being silently refunded.

## Executable coverage

`cargo test -p latent-capabilities --lib --locked` covers guessed/cross-session
handles, publication/catalog/principal substitution, slot reuse, revocation,
deferred dispatch, limits, required multi-dimensional budgets, detached work,
typed buffers, provider failure/unwind and foreign responses.
`cargo test -p latent-wasmtime --test broker --locked` executes a tiny binary
component through the real linker, reuses a warm cell, revokes during a host
call, cancels between calls, rejects foreign/missing owners before Store creation
and checks resource reclamation. Neither suite requires external language
toolchains or a load campaign.

The [bounded asynchronous I/O substrate](async-host-io.md) adds queue ownership,
fixed-capacity buffers, stream backpressure and waiting/cleanup observations.
Its canonical async guest tests use a test-only provider. Bounded shared provider
pools, production plan compilation and concrete external providers remain their
subsequent Phase 3 tickets. This
boundary does not claim hostile multitenant qualification, durable outboxes,
transactions or universal exactly-once external effects.
