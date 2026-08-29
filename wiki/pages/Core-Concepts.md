<!-- LSF-WIKI-MANAGED -->
# Core concepts

LSF separates durable logical identity from temporary execution allocation.
That distinction is the foundation for the resource model.

| Term | Meaning |
|---|---|
| Service | Stable logical name and contract identity; not a process. |
| Release | Immutable capsule artifact identified by a digest. |
| Revision | A release combined with mutable deployment configuration. |
| Route | A rule selecting a revision for new work. |
| Activation | One bounded execution of a revision, function, input, identity, budget, and deadline. |
| Execution cell | A reusable generic node allocation slot, temporarily leased by an activation. |
| Capsule | Component binary plus manifest, contract graph, provenance, and trust information. |
| Domain error | A result declared by a service’s WIT contract. |
| Platform error | Infrastructure failure represented in the stable platform error model. |

## Dormant does not mean resident

The intended model is:

```text
Service → release metadata + policy + route information
Invocation → temporary activation → generic leased execution cell
```

An idle service must not obtain its own worker, listener, process, thread,
connection pool, or Wasmtime store merely because it is registered.

## Phase 0 versus target architecture

Phase 0 proves one local execution slice: a trusted echo capsule is prepared,
leased into a fixed generic pool, invoked in a fresh Wasmtime store, and
cleaned up. It does **not** implement service registration, revision routing,
admission policy, persistent deployment state, or remote invocation.

Those concepts remain part of the documented target architecture. They should
not be described as runtime features until their phase-specific code,
contracts, and evidence exist.

## Bounded ownership

Node-owned state may be fixed or explicitly bounded: runtime workers, cell
capacity, queue length, prepared-component cache entries/bytes, and retained
logs. Activation-owned state exists only while a lease is active: store,
instance, host context, temporary payloads, cancellation registration, and
budget accounting.

Safe reuse requires a positive cleanup proof. If the backend cannot establish
that state is reusable, the cell is quarantined rather than silently reused.

## Error layers

Domain errors belong to the capsule contract; callers can handle them as part
of normal business behavior. Platform errors describe failed execution,
containment, resource enforcement, or infrastructure. A client surface must
preserve the distinction rather than encoding a domain failure as an apparent
successful payload.

See [Activation lifecycle](Activation-Lifecycle), [Execution cells](Execution-Cells),
and the [platform error model](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/platform-errors.md).
