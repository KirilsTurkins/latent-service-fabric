# Cluster topology

This is a planned cluster design. The current
[standalone Linux node](../reference/standalone-node.md) has local durable
catalogs, authenticated loopback RPC and optional shared HTTP ingress.
Cluster control, remote invocation, workload mTLS and PostgreSQL are not
implemented. Existing Docker/Kubernetes measurements run the standalone node;
they do not establish a distributed control plane or production high availability.

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
The wire/storage implementation and old-reader behavior remain unimplemented.

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

This is a future failover contract, not a property supplied by the standalone
node's local database. Phase 5 must qualify replication, durable ownership and
fencing before another node can recover a command or dispatch its effects.
Losing the only storage root has no current automatic failover path.

- Unstarted work may be rerouted only while preserving its exact target and
  original authority/deadline constraints; a route pin is not acceptance.
- Stateless retry remains an explicit caller/policy decision. Unknown external
  outcome is no proof that a mutation is safe to repeat.
- A transactional timeout or node loss requires recovery by original command
  identity. Only durable abort evidence can establish zero commitment; loss of
  an activation does not establish that its commit failed.
- Committed state/outbox durability follows the selected replicated storage
  contract, not the lifetime of an execution cell or the route snapshot.
- Future entity ownership needs fencing beyond elapsed lease time. Durable
  workflow continuations remain Phase 6 and are not supplied by local async waits.

## Finite control-plane outage behavior

The accepted [freshness contract](../../rfcs/0004-route-and-authorization-freshness.md)
keeps ordinary resolution local and bounds disconnected authorization separately
from route retention. Its planned lease/disconnection policy defaults to
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

The [Cluster implementation handoff](cluster-freshness-handoff.md) assigns protocol, storage,
clock, node, runtime and conformance responsibilities and records the required
outage/revoke/restart/reordering matrix. Those distributed paths are not yet
implemented. The current local lifecycle fence is not a remote-freshness claim.
