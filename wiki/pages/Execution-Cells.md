<!-- LSF-WIKI-MANAGED -->
# Execution cells

An execution cell is a reusable generic allocation slot owned by a node. It is
not a service instance, a per-service worker, or a dormant process.

## Current Phase 0 pool

`FixedCellPool` establishes one configured capacity at construction. Idle slots
hold only stable cell identity and reuse generation. They do not retain a
capsule, tenant, activation, Wasmtime engine/store, listener, connection, or
operating-system thread.

The pool provides:

- fixed capacity and bounded FIFO waiting;
- affine, non-cloneable leases;
- deterministic cancellation and deadline removal while queued;
- release only after explicit reusable cleanup;
- one-way quarantine when reuse cannot be proven safe; and
- constant-time observations of capacity, availability, active leases, queue
  depth, and quarantined cells.

For every stable state:

```text
available + active_leases + quarantined = capacity
queue_depth = 0 after a completed measured workload
```

## Ownership model

An independent `CellPool` implementation remains possible through the public
trait seam, but it must retain lifecycle authority for leases it creates. A
stale, forged, duplicated, or cross-pool lease return cannot increase available
capacity. Dropping a live lease is conservative: it quarantines rather than
silently returning a possibly contaminated cell to the pool.

## What Phase 0 measures

The spike and baseline observe fixed configured capacity, a bounded queue,
release/quarantine accounting, recovery after failures, and return to an idle
state. It does not implement production scheduling, priorities, fairness
across services, multiple size classes, autoscaling, repair/replacement, or
cluster placement.

See the [fixed-cell-pool guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/fixed-cell-pool.md)
and [execution-cell architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/architecture/execution-cells.md).
