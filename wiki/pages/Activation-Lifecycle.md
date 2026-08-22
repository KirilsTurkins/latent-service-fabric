# Activation Lifecycle

> **Document role:** Explanatory lifecycle guide. The canonical state machine, commit protocol, and platform error model live under `docs/protocol/`.

## State machine

```text
RECEIVED
  → RESOLVED
  → ADMITTED
  → QUEUED
  → MATERIALIZING
  → RUNNING
      ↔ SUSPENDED
  → PREPARING_COMMIT
  → COMMITTED
  → EFFECTS_PENDING
  → COMPLETED
```

Terminal exits include rejection, cancellation, deadline exhaustion, resource exhaustion, guest traps, state conflicts, dependency failures, and platform failures.

## 1. Receive

Shared ingress validates the basic envelope and creates or propagates activation identity, caller context, trace context, deadline, and request metadata. Malformed or oversized payloads should fail before unsafe host operations.

## 2. Resolve

The node's local immutable route snapshot selects an exact revision. Resolution pins:

- revision identifier;
- release digest;
- route generation;
- contract and function;
- capability-policy digest;
- execution policy.

An in-flight activation does not switch revisions when a newer route snapshot arrives.

## 3. Admit

Admission runs before cell allocation. It evaluates identity, grants, quotas, payload limits, deadline feasibility, trust-class capacity, requested cell class, and overload state.

Rejection is a normal platform outcome, not a reason to create a service-specific worker.

## 4. Queue and schedule

Accepted work enters bounded queues. The scheduler applies tenant fairness, priorities, deadlines, locality, state affinity, and trust-class restrictions. Child work inherits bounded portions of the parent's remaining budgets.

## 5. Materialize

The node obtains or prepares the exact immutable artifact using bounded cache tiers:

```text
metadata → raw capsule → AOT artifact → mapped code → prepared imports → snapshot
```

Every tier is globally reclaimable. A cache entry is not a running service instance.

## 6. Bind capabilities

The runtime intersects capsule imports, deployment grants, and caller authorization. It installs opaque activation-scoped handles for permitted host capabilities and provider bindings.

## 7. Run or suspend

Guest code executes with bounded CPU fuel, wall deadline, memory, stack, call depth, host-call count, payload sizes, and descendant budgets.

- Ordinary asynchronous waits release the compute worker while retaining logical activation state.
- Durable workflow suspension persists an explicit continuation and releases the full cell and guest store.

## 8. Prepare and commit

Guest completion may produce output, state mutations, and effect intents. The commit boundary:

1. validates the state read set;
2. atomically persists state mutations and effect-outbox records where promised;
3. creates a durable commit receipt;
4. transitions to committed.

The platform returns success only after reaching the contractually promised commit level. External effects may remain pending although their intents are durable.

## 9. Reclaim

On completion, trap, cancellation, deadline, or permanent failure, the platform stops guest execution, revokes handles, releases transaction ownership, clears buffers, finalizes accounting, removes activation identity, and resets backend memory before returning the cell.

## Cancellation and ambiguity

Cancellation is advisory until the backend acknowledges it. A caller timeout or lost response does not prove that a state commit or external operation did not occur.

Side-effecting clients need:

- stable idempotency identities;
- activation or commit-status inspection;
- retry behavior based on operation semantics rather than transport failure alone.

## Domain errors and platform errors

Domain errors are declared by the called WIT contract. Infrastructure failures use stable platform codes such as `unavailable`, `deadline-exceeded`, `resource-exhausted`, `permission-denied`, `state-conflict`, `guest-trap`, or `route-unavailable`.

A retryability hint never overrides idempotency rules.

## Canonical sources

- [Activation lifecycle protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/activation-lifecycle.md)
- [Activation commit protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/commit-protocol.md)
- [Platform error model](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/platform-errors.md)
- [Data-plane architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/data-plane.md)

Continue with [[State-and-Effects|State and effects]] and [[Execution-Cells|Execution cells]].
