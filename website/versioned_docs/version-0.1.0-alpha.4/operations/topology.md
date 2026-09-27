# Operational topology

The [standalone Linux node](../reference/standalone-node.md) runs capsules and
keeps their published versions, deployments and routes on local storage. It
provides package verification, revocation, bounded caches, audit, canary updates
and rollback. Optional [HTTP and blob providers](../reference/standalone-providers.md)
let permitted capsules use external services and local objects. Shared application
ingress serves [static sites](../component-development/static-sites.md) and
[Angular applications](../component-development/angular-build.md).

Cluster placement, transactional application state and durable workflows are
not available. Plan this installation as one node.

## Implemented single-node topology

```text
latent CLI / generated management clients
  -> one authenticated loopback gRPC listener
      -> fixed control runtime and management admission
          -> authoritative release catalog + optional supply-chain owner
          -> one deployment/route/rollout catalog transaction
          -> optional shared rollout coordinator
          -> optional durable audit worker
      -> immutable route pins + activation admission
          -> fixed execution-cell pool
          -> bounded compiler workers and resident prepared cache
              -> optional isolated compiler child per admitted job
              -> optional authenticated native cache
          -> one activation cleanup driver + bounded telemetry

latent package push/pull -> external OCI registry
```

The CLI transfers package bytes over RPC; its source/evidence directories remain
separate from node storage. The OCI registry is an external distribution service,
not a database that the node consults on Invoke. Registry credentials are separate
from node credentials. The local management listener is still loopback plaintext
gRPC; TLS in the registry workflow does not turn it into a remotely exposed node
endpoint.

Enforced startup creates one supply-chain owner and starts the existing clock/load
sampler before catalog recovery. Optional audit opens before recovery and retains
accepted work independently of RPC waiters. Rollout and managed deployment audit
reconciliation dispatches through retained receipts before the generic fallback.
Omitting rollout RPCs preserves durable history and routes. Corrupt authoritative
content prevents startup; verified ineligible desired releases retain denying
routes so management can remove or update them.

There is one optional rollout worker, no worker per rollout or service, and no
extra worker for managed deployment mutations. Canary capture uses one bounded
hub and the same trusted clock as activation admission. It adds no timer or
worker. Promotion and rollback require explicit commands. Invocation reads pinned
routes and current eligibility; it does not append audit records or acquire the
rollout coordinator's locks.

Shutdown stops producers and joins rollout before audit, then releases the outer
control runtime. Compiler cancellation retains jobs and reservations until actual
completion or child exit. Lost waiters and expired deadlines do not prove stopped
filesystem work. Owner, queue and retained response counts participate in clean
shutdown reporting; an external process supervisor provides the hard termination
boundary for noncooperative operating-system work.

## Capacity planning

Plan each finite ownership domain separately:

- Fixed runtime/control workers, connection/RPC gates, cells and bounded queues.
- Prepared entry, source, metadata, image and waiter limits, plus cold compiler jobs.
- Authoritative catalog metadata, rollout rows/stages and separate finite operation receipt rings.
- Audit disk/record/queue limits and retained query responses; the journal does not prune automatically.
- Optional native blob/receipt storage, staging and read leases, compiler output and page-rounded live mappings.
- Canary windows, live/retained samples, snapshot owners and activation status retention.

Evicting a cache entry cannot refund code still held by a ready or active owner.
An authenticated native cache hit still requires current catalog-owned source,
proof and exact compatibility. Cache files cannot restore revoked authority.
Logical byte counters, native mappings and total process RSS describe different
resources. Do not plan one heap, connection pool or listener per service.

Measure capacity with your own workload, including the providers, auditing and
package verification you enable. Cache sizes and execution-cell counts are
limits to configure, not throughput guarantees. The
[resource reports](../testing/phase3-resource-recovery.md) describe the workloads
used for development measurements and their limitations.

## Observability and future production topology

Current inventory, [telemetry](../telemetry.md), [audit](../phase-2-audit.md) and
[canary observations](../phase-2-canary-observation.md) expose distinct evidence.
Audit scan completion does not erase dropped observations, unknown outcomes or
prior-session loss. Healthy promotion uses sealed attributed observations, not
arbitrary dashboard counters. No hosted dashboard or general OTLP exporter is
included.

The standalone configuration installs only the providers listed in its
[provider reference](../reference/standalone-providers.md). Additional providers
have their own integration instructions; adding an arbitrary provider name to
the node configuration does not install one. PostgreSQL-backed control, remote
placement, transactional state and durable workflow suspension are planned
features; see the [roadmap](../roadmap.md).
