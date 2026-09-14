# Identity and capability architecture

The current node authenticates configured bearer credentials on its
loopback RPC listener and applies tenant-scoped management, invocation, status
and cancellation authorization. Its guest imports are limited to context, log
and monotonic/wall clocks. See the [node credential model](../reference/standalone-node.md)
and [capability implementation](../runtime/capabilities.md). Phase 2 also binds
execution to current release lifecycle and, in enforced mode, verified signing
authority. Phase 3 adds the [sealed activation broker](../runtime/capability-broker.md)
in explicit managed embeddings; coherent standalone provider installation,
bounded delegation and external providers remain in progress. Node workload mTLS remains part of the later cluster
architecture. See the [security boundary](security.md) and [roadmap](../roadmap.md).

The delivered [capability policy owner](../runtime/capability-policies.md) binds
tenant-scoped immutable policy revisions and provider selections to real
publication eligibility. Its sealed decisions require a final currentness check;
updates/revocations invalidate held authority. Required policies and additional
restrictions intersect. The broker connects these rows to activation-owned handle
tables, guarded call admission, the original budget ledger and retained work/
result ownership. The standalone binding compiler and concrete external provider
implementations are subsequent Phase 3 tickets.

## Identity layers

LSF distinguishes:

- transport peer identity,
- authenticated caller principal,
- logical tenant and service identity,
- node workload identity,
- delegated child-call identity,
- administrator identity.

A future remote child call must carry a bounded delegation rather than the caller's unrestricted original credential. Phase 1 root/parent IDs are correlation metadata and do not grant delegated authority.

## Broker authorization

Sealed decisions bind the trusted principal, exact operation/resource, service
revision, route generation, publication, current policies and installed provider
configuration. Policy ceilings narrow actual operation budgets; they do not
create a new ledger. Bind and call start both recheck currentness. No authority
fence crosses provider I/O or an await. Detailed provider audit, delegation and
placement behavior remain their respective Phase 3 implementation tickets.

## Capability intersection

A guest import becomes usable only when requested by the immutable capsule, granted by deployment policy, and permitted for the current principal and operation.

## Broker handle properties

A handle is a slot/incarnation lookup inside one affine activation session. It
cannot transfer authority to another session or publication. Bind fixes the
operation and exact resource; every call rechecks current policy/provider
revisions and the effective deadline. Session termination invalidates lookup
slots, while actual provider work and result owners retain their charges until
destruction. Cell reuse requires cleanup proof. Descriptive DTOs, claims and
cached code are not grants. Explicit descendant delegation remains #208/#209.

## Node identity

Node-to-node calls require mutually authenticated workload identity. Logical caller identity and node transport identity are carried and audited separately.
