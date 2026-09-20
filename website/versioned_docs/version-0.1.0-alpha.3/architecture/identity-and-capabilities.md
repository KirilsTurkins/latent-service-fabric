# Identity and capability architecture

The current node authenticates configured bearer credentials on its
loopback RPC listener and applies tenant-scoped management, invocation, status
and cancellation authorization. Its guest imports are limited to context, log
and monotonic/wall clocks. See the [node credential model](../reference/standalone-node.md)
and [capability implementation](../runtime/capabilities.md). Phase 2 also binds
execution to current release lifecycle and, in enforced mode, verified signing
authority. Phase 3 plans the general capability broker, bounded delegation and
external providers below. Node workload mTLS remains part of the later cluster
architecture. See the [security boundary](security.md) and [roadmap](../roadmap.md).

## Identity layers

LSF distinguishes:

- transport peer identity,
- authenticated caller principal,
- logical tenant and service identity,
- node workload identity,
- delegated child-call identity,
- administrator identity.

A future remote child call must carry a bounded delegation rather than the caller's unrestricted original credential. Phase 1 root/parent IDs are correlation metadata and do not grant delegated authority.

## Planned broker authorization

Authorization decisions bind principal, action, resource, deployment generation, route generation, capability policy, and relevant request attributes. Decisions can attach obligations such as reduced budgets, redaction, audit requirements, or placement constraints.

## Planned capability intersection

A guest import becomes usable only when requested by the immutable capsule, granted by deployment policy, and permitted for the current principal and operation.

## Planned broker handle properties

Capability handles must be opaque, activation-scoped, non-transferable unless explicitly delegated, operation-scoped, quota-bound, expiring, and revocable. The broker must prevent use after activation completion. Existing context, log and clock bindings already check their activation context; descriptive policy and handle DTOs alone do not grant provider authority.

## Node identity

Node-to-node calls require mutually authenticated workload identity. Logical caller identity and node transport identity are carried and audited separately.
