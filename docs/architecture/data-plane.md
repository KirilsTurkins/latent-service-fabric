# Data-plane architecture

The delivered data plane is the single-node stateless composition described in
[the Phase 1 completion report](../phase-1-completion.md). Its
[performance extension](../phase-1-extension-completion.md) adds bounded cold
preparation, warm identity/cache reuse and transport cleanup while retaining
the same activation ownership and admission boundaries.

## Current invocation path

```text
authenticated loopback invocation RPC
  → pinned local route and policy
  → admission controller
  → bounded repository-backed preparation readiness
  → fair scheduler
  → cell assignment and prepared-use materialization
  → context/log/clock capability binding
  → fresh Wasmtime store and execution
  → contained cleanup and cell release or quarantine
  → finalized accounting, status, result and telemetry
```

## Shared ingress

Phase 1 supplies direct RPC. HTTP, event, queue, timer and blob adapters remain
planned. Capsules never own network listeners or consumer loops.

## Route resolution

Resolution pins the node's immutable route and policy snapshot and selects an
exact revision. Remote propagation of that identity is a later-phase contract;
Phase 1 does not forward calls between nodes.

## Admission

Admission occurs before a cell is allocated. It checks identity, policy, payload size, quota, deadline feasibility, trust-class capacity, requested cell class, and overload state.

## Scheduling

The scheduler uses bounded class queues, round-robin tenant fairness, admitted
priorities, deadlines and aging. Admission fixes the permitted trust/cell class.
Preparation readiness completes before scheduler enqueue, so cold arrivals are
not guaranteed FIFO cell eligibility. Artifact-locality placement and state
affinity remain planned. Overload never creates service-specific threads or processes.

## Materialization

Phase 1 verifies local artifacts and retains immutable compiled code in a bounded
shared prepared cache. Warm verified identity lookup avoids component I/O and
full metadata traversal. Cold directory reads and compilation run on fixed
compiler workers with bounded jobs, inputs and waiters; the compiler retains
ownership until native work returns even if callers cancel. A readiness pin
owns no cell or guest store. The [runtime reference](../runtime/wasmtime.md)
documents cache, preparation and in-flight accounting independently.

The broader future cache-tier model is:

```text
metadata → raw capsule → AOT artifact → mapped code → prepared imports → snapshot → fused derivative
```

Mapped snapshots and fused derivatives are not implemented. Cache entries are
reclaimable node resources, but in-flight pins may outlive eviction. No entry
constitutes a required running service instance.

## Capability binding

The deployment's grants, declared imports and admitted policy constrain the
supported context/log/clock interfaces. Each activation receives fresh host
state and handles. General network, blob, state, secret and child-call providers
remain unavailable and their imports fail explicitly.

## Execution

A generic cell receives a fresh activation context and isolated store. Phase 1
enforces CPU fuel, monotonic wall/deadline, aggregate linear memory and accepted
log-byte budgets, plus node stack, context, transfer and value-codec limits.
Later-phase budget dimensions must be zero; descendant call accounting awaits
child-call implementation. See [resource budgets](../runtime/resource-budgets.md).

## Planned commit and effects

Guest code returns output, state mutations, and effect intents. State and outbox records commit atomically where the selected state backend supports it. External effects are dispatched by shared providers with stable idempotency identities.

That transactional path is not part of Phase 1. Current stateless calls return
output or a typed guest/platform failure without guest state commits or outboxes.

## Reclamation

On completion, cancellation, trap, deadline, or permanent failure, the store and
activation-scoped capability handles are dropped and activation resources are
reclaimed. Returning a cell to the generic pool requires affirmative backend
cleanup proof and successful pool disposition; uncertain cleanup quarantines it.
After transport loss, standalone's bounded supervisor continues the same
activation owner under its original deadline to obtain that proof. A terminal
outcome alone does not establish reuse safety.
