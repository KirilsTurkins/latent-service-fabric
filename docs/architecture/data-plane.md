# Data-plane architecture

## Invocation path

```text
shared ingress
  → local route resolver
  → admission controller
  → fair scheduler
  → artifact/AOT materializer
  → capability binder
  → execution cell
  → state commit coordinator
  → effect outbox
  → result and telemetry
```

## Shared ingress

HTTP, direct RPC, event, queue, timer, and blob triggers terminate in shared ingress adapters. Capsules never own network listeners or consumer loops.

## Route resolution

Resolution uses the node's immutable snapshot and selects an exact revision. The invocation envelope carries the selected release digest and route generation when crossing nodes.

## Admission

Admission occurs before a cell is allocated. It checks identity, policy, payload size, quota, deadline feasibility, trust-class capacity, requested cell class, and overload state.

## Scheduling

The scheduler uses bounded queues, tenant fairness, priorities, deadlines, artifact locality, state affinity, and trust-class constraints. It never responds to overload by creating service-specific threads or processes.

## Materialization

Materialization proceeds through bounded shared cache tiers:

```text
metadata → raw capsule → AOT artifact → mapped code → prepared imports → snapshot → fused derivative
```

Every tier is globally reclaimable. No cache entry constitutes a required running service instance.

## Capability binding

The deployment's grants are intersected with the capsule's requested imports and the invocation principal's policy. Opaque activation-scoped handles are supplied to guest imports.

## Execution

A generic cell receives a fresh activation context and isolated store. Guest execution is bounded by CPU fuel, wall deadline, memory, stack, call depth, host-call count, payload sizes, and descendant budgets.

## Commit and effects

Guest code returns output, state mutations, and effect intents. State and outbox records commit atomically where the selected state backend supports it. External effects are dispatched by shared providers with stable idempotency identities.

## Reclamation

On completion, cancellation, trap, deadline, or permanent failure, the store and activation-scoped capability handles are dropped, dirty pages are reclaimed, and the cell returns to the generic pool.
