# Activation lifecycle protocol

This is the cross-phase target protocol. The current
[stateless lifecycle](../activation-lifecycle.md) runs activations through
`Received`, `Resolved`, `Admitted`, `Queued`, `Materializing`, and `Running`, then
publishes a separate terminal state. Phase 2 adds current release authority
checks and controlled route publication without changing that stateless result
model. Durable commit and effects below belong to Phase 4; durable suspension and
workflow continuation belong to Phase 6. See the [roadmap](../roadmap.md).

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

Terminal exits may occur as `REJECTED`, `CANCELLED`, `DEADLINE_EXCEEDED`, `RESOURCE_EXHAUSTED`, `GUEST_TRAP`, `STATE_CONFLICT`, `DEPENDENCY_FAILED`, or `PLATFORM_FAILED`.

## Pinning

Resolution pins revision ID, release digest, route generation, contract/function, capability-policy digest, and execution policy before the activation enters the queue.

## Cancellation

Cancellation is advisory until acknowledged by the execution backend. A caller timeout does not prove that a state commit or external operation did not occur. Side-effecting calls therefore require stable idempotency identities and status inspection where applicable.

## Suspension

Ordinary async suspension keeps the activation logical context but releases the compute worker. Durable workflow suspension persists an explicit continuation and releases the complete execution cell and guest store.

## Journal

In the target protocol, lifecycle events are monotonically sequenced per activation and contain only non-secret metadata. Commit, effect, security and failure transitions require durable records according to policy. The current bounded invocation status journal and optional [Phase 2 audit journal](../phase-2-audit.md) have separate retention and loss contracts; Phase 2 does not emit a mandatory durable audit record for every Invoke.
