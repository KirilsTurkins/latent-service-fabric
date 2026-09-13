# Cluster topology

This is the intended Phase 5 clustered topology. The current
[standalone Linux node](../reference/standalone-node.md) uses one node process,
local durable catalogs and a loopback RPC listener. Phase 2 delivers authenticated
OCI transfers and trusted package admission without a cluster control plane.
Cluster control, remote invocation, workload mTLS and PostgreSQL remain planned;
guest state belongs to Phase 4 and durable workflows to Phase 6. See the
[roadmap](../roadmap.md). The extension's
[Docker/Kubernetes benchmarks](../phase-1-extension-completion.md#kubernetes-112)
run that same standalone product inside containers; they do not implement this
control plane or establish production HA.

## Planned control plane

Two or more `latent-control` instances may share PostgreSQL and an OCI registry. They expose management APIs and distribute route snapshots. A custom consensus system is not required for the initial architecture.

## Planned data plane

Every `latentd` node can execute any compatible release it can retrieve, verify, prepare, and admit under its trust and placement policies.

## Node identity

Node and control communication requires mutually authenticated transport. The architecture supports SPIFFE-compatible workload identities but does not require a specific identity provider in the interface scaffold.

## Remote invocation

A future remote call carries the exact scoped publication, package/component
identities, revision, contract, function, route generation/digest, principal
delegation, trace context, remaining deadline, delegated resource budget and
idempotency information. The receiving node independently validates current
local authority and its own authorization lease for the exact target. A sender's
cached route or signature cannot replace that check.

The receiving node executes the exact publication or rejects the call. It cannot
substitute another publication with identical component bytes or a newer route.
The wire/storage implementation and old-reader behavior remain Phase 5 work.

## Availability

Availability is expressed as eligible nodes and cached artifact copies rather than running replicas:

```text
minimum cached copies
minimum zones
allowed trust classes
allowed architectures
required accelerators or CPU features
```

## Node failure

- unstarted queued work may be re-routed,
- stateless work may be retried only under retry policy,
- uncommitted state is discarded,
- committed state remains durable,
- effect intents in the outbox remain durable,
- entity leases expire,
- workflow continuations remain persisted.

## Finite control-plane outage behavior

The accepted [freshness contract](../../rfcs/0004-route-and-authorization-freshness.md)
keeps ordinary resolution local and bounds disconnected authorization separately
from route retention. Its initial Phase 5 lease/disconnection policy defaults to
30 seconds with a 300-second hard ceiling, intersected with stricter configured
bounds and underlying expiries. These are selected future settings, not current
standalone options or observed availability guarantees.

Known revocations deny at local guarded start. Unseen remote revocations cannot
be immediate during a partition; existing authority expires conservatively and
then denies new starts. Accepted activations may finish under their finite
execution limits. Queued/ready work and new descendants recheck current
permission. Restart requires a new-boot checkpoint and lease; retained snapshots
cannot revive authorization. Reconnect reconciles floors, time and exact
publication authority before resuming.

The [Phase 5 handoff](cluster-freshness-handoff.md) assigns protocol, storage,
clock, node, runtime and conformance responsibilities and records the required
outage/revoke/restart/reordering matrix. Those distributed paths are not yet
implemented. The current local lifecycle fence is not a remote-freshness claim.
