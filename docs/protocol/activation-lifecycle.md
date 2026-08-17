# Activation lifecycle protocol

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

Lifecycle events are monotonically sequenced per activation and contain only non-secret metadata. Journaling may be sampled for low-value stateless calls but commit, effect, security, and failure transitions require durable records according to policy.
