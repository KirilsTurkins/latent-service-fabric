# Operational topology

The development topology is implemented by the
[standalone Linux node](../reference/standalone-node.md): local catalogs,
invocation/management RPCs, fixed execution resources and bounded telemetry.
Later production topologies remain roadmap work. The finite
[Phase 0 spike](../phase-0-spike.md) retains its separate evidence boundary.

## Delivered Phase 1 standalone topology

```text
standalone latentd
├── embedded control modules
├── local route snapshot
├── local artifact directory
├── bounded activation status and telemetry
└── fixed execution-cell pool
```

## Planned production topology

This topology belongs to later phases; Phase 1 uses local storage and stateless
execution without PostgreSQL, OCI, state/effect providers, or clustering.

```text
management LB
  → latent-control × 2–3
      → PostgreSQL
      → OCI registry

shared ingress
  → latentd nodes
      → state backend
      → effect providers
      → OTLP collector
```

## Capacity planning

For the delivered standalone node, plan capacity by:

- cell classes and count,
- compute worker count,
- I/O concurrency,
- global cache bounds,
- expected active activation concurrency,
- bounded cold-compilation jobs and waiters,
- retained catalog metadata and activation journal bounds.

Provider pools, trust-sharded execution processes, state locality and cross-node
placement belong to later topology planning; configuring the Phase 1 node does
not create those services.

Do not plan by one heap, connection pool, or listener per service.

The [measured tuning guidance](../phase-1-extension-completion.md#tuning-and-closure)
separates active component working sets, prepared-cache capacity and
available cells from dormant catalog size. Budget queue/admission headroom
and cleanup separately. Infrastructure comparisons retain native resource
partitioning, LSF pooling and observed effective CPU caps; they do not
establish an isolated orchestration cost or a production capacity limit.

## Observability and dashboard planning

Phase 1 exposes bounded [telemetry and inventory](../telemetry.md); it does not
ship a hosted dashboard or OTLP exporter. Existing observations support local
cell/queue/cache/activation health inspection. Operator-built dashboards can
combine these with process/resource probes:

- fixed runtime RSS versus activation RSS,
- active/available cells by class,
- queue delay by tenant and priority,
- materialization/AOT cache hit rates,
- activation success, trap, timeout, and cancellation rates,
- process/thread/socket counts versus registered releases.

State conflicts, effect retries and remote route-generation lag become useful
when the corresponding state/effect and cluster features are implemented. The
[extension report](../phase-1-extension-completion.md) closes the measured Phase 1
campaigns with their limitations; use those scoped results as sizing evidence,
not a promise that all workloads meet the same warm latency or RSS ceiling.
