# latent-scheduler

Bounded fair local scheduling over fixed-capacity generic execution-cell pools. `LocalScheduler` manages tenant/class queues and owns cancellation/deadline-aware assignments; `FixedCellPool` owns cell leasing and quarantine. Cluster placement remains an abstract port, with a local placement helper for the standalone case.

Cells belong to the node, not to dormant deployments. A queue entry or diagnostic observation cannot manufacture extra execution capacity.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | CellLease, scheduling/placement requests and scheduler/pool contracts. |
| [src/local/mod.rs](src/local/mod.rs) | LocalScheduler configuration, fair dispatch, observations and shutdown. |
| [src/local/queue.rs](src/local/queue.rs) | Bounded intrusive tenant queues and finite slot storage. |
| [src/local/immediate.rs](src/local/immediate.rs) | One fair dispatch attempt for descendants, avoiding indefinite waits behind their own parents. |
| [src/fixed_pool/mod.rs](src/fixed_pool/mod.rs) | Fixed cell capacity, acquisition, lease lifecycle and quarantine. |

## Execution and ownership

1. Receive admitted work carrying its original quota permit, deadline and cancellation owner.
2. Apply bounded per-class tenant scheduling; cancelled or expired waiters cannot receive a later usable lease.
3. Move the lease into execution. A waiting parent retains its own cell; a local child gets a fair immediate attempt rather than an overflow cell.
4. Explicitly return a proven-clean cell or quarantine it. Dropping an unresolved live lease does not assert safe reuse.

## Integration boundaries

Scheduling does not execute guests, authorize capabilities or make cluster placement implemented. Preserve the distinction between available pool capacity, queued work and received assignments. Destruction of cancellation owners happens outside scheduler locks so callbacks cannot invert the ownership boundary.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md), [latent-admission](../latent-admission/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-node](../latent-node/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-scheduler.lib.latent-scheduler
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`capacity_is_fixed_and_concurrent_acquisition_is_bounded`](src/fixed_pool/tests/behavior.rs)
- [`bounded_queue_rejects_excess_work_deterministically`](src/fixed_pool/tests/behavior.rs)
- [`cancelled_waiter_never_receives_a_later_lease`](src/fixed_pool/tests/behavior.rs)
- [`expired_waiter_never_receives_a_later_lease`](src/fixed_pool/tests/behavior.rs)

Integration targets: [tests/cell_pool_seam.rs](tests/cell_pool_seam.rs), [tests/fair_scheduler.rs](tests/fair_scheduler.rs).

## Related documentation

- [Phase 0 fixed execution-cell pool](../../docs/development/fixed-cell-pool.md)
- [Execution-cell architecture](../../docs/architecture/execution-cells.md)
- [Isolated local service invocation](../../docs/runtime/local-service-invocation.md)
- [Phase 0 activation containment](../../docs/development/activation-containment.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
