# Identity and capability architecture

Phase 1 authenticates configured bearer credentials on the standalone node's
loopback RPC listener and applies tenant-scoped management, invocation, status
and cancellation authorization. Its guest imports are limited to context, log
and monotonic/wall clocks. See the [node credential model](../reference/standalone-node.md)
and [capability implementation](../runtime/capabilities.md). Node workload mTLS,
delegated child calls and general external capability providers below remain
later-phase design contracts.

## Identity layers

LSF distinguishes:

- transport peer identity,
- authenticated caller principal,
- logical tenant and service identity,
- node workload identity,
- delegated child-call identity,
- administrator identity.

A future remote child call must carry a bounded delegation rather than the caller's unrestricted original credential. Phase 1 root/parent IDs are correlation metadata and do not grant delegated authority.

## Authorization

Authorization decisions bind principal, action, resource, deployment generation, route generation, capability policy, and relevant request attributes. Decisions can attach obligations such as reduced budgets, redaction, audit requirements, or placement constraints.

## Capability intersection

A guest import becomes usable only when requested by the immutable capsule, granted by deployment policy, and permitted for the current principal and operation.

## Handle properties

Capability handles are opaque, activation-scoped, non-transferable unless explicitly delegated, operation-scoped, quota-bound, expiring, and revocable. The runtime prevents use after activation completion.

## Node identity

Node-to-node calls require mutually authenticated workload identity. Logical caller identity and node transport identity are carried and audited separately.
