# Operational topology

## Development

```text
latentd --standalone
├── embedded control modules
├── local route snapshot
├── local artifact directory
├── local state backend
└── fixed execution-cell pool
```

## Initial production

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

Plan capacity by:

- cell classes and count,
- compute worker count,
- I/O concurrency,
- global cache bounds,
- provider pool bounds,
- expected active activation concurrency,
- trust-class partitioning,
- artifact and state locality.

Do not plan by one heap, connection pool, or listener per service.

## Required dashboards

- fixed runtime RSS versus activation RSS,
- active/available cells by class,
- queue delay by tenant and priority,
- materialization/AOT cache hit rates,
- activation success, trap, timeout, and cancellation rates,
- state conflict and effect retry rates,
- route-generation lag,
- process/thread/socket counts versus registered releases.
