# latent-state

Concrete protected transactional storage foundation. A redb-backed `EmbeddedStore` holds bounded record families in one atomic engine; `ProtectedStoreOwner` confines initialization, views, writes and retirement to fixed workers. Higher layers use optimistic sessions, namespace lifecycle, tenant accounting and deliberately paused recovery over that same owner.

The generic `StateBackend`/entity lease ports remain available, but they do not describe the full implementation. This crate does not expose an arbitrary persistent language heap, userfault pager or durable workflow runtime.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/embedded.rs](src/embedded.rs) | Bounded redb record families, MVCC ReadView, AtomicBatch, expectations and final acceptance fence. |
| [src/protected_store.rs](src/protected_store.rs) | Actual protected engine owner, operation/view custody, startup, close/quarantine and asynchronous drain. |
| [src/store_io.rs](src/store_io.rs) | Fixed workers, finite queues and response/retirement ownership for blocking native work. |
| [src/session/mod.rs](src/session/mod.rs) | Affine optimistic command/query sessions over the original snapshot and bounded staged values. |
| [src/namespace.rs](src/namespace.rs) | Durable namespace metadata, incarnations, schema/history fences and destruction floors. |
| [src/reservation.rs](src/reservation.rs) | Logical disposition capacity reserved in the same engine transaction. |
| [src/tenant.rs](src/tenant.rs) | Explicit tenant accounting and checked same-envelope counter updates. |
| [src/entity_lanes.rs](src/entity_lanes.rs) | Invocation-local entity eligibility; distinct from durable deduplication. |
| [src/recovery.rs](src/recovery.rs) | Offline logical snapshots, fixed migration, reviewed restore and explicit resume. |
| [src/store_identity.rs](src/store_identity.rs) | Physical database identity and protected external checkpoint descriptions. |

## Execution and ownership

1. Open a protected descriptor, install actual native/startup capacity and bind the store identity before publishing consumers.
2. Create bounded read views on fixed workers. Every session retains its original view identity, namespace scope and age limit.
3. Build one bounded batch with expected originals, mutations and required accounting/reservation deltas; check current host acceptance immediately before durable commit.
4. Distinguish pre-commit rejection/conflict from uncertain commit I/O. Retain native operations and result bytes even if a waiter disappears.
5. For recovery, establish exclusive physical custody and paused admission. Import/migrate/review under the original workers, then resume only through an explicit current approval.

## Integration boundaries

`latent-commit` assembles complete command/state/result/outbox envelopes; `latent-effects` owns provider dispatch; `latent-node` supplies activation-scoped authority and guest integration. Store/session IDs and historical receipts are preconditions, not grants. Dropping a read waiter, expiring a claim or timing out shutdown cannot prove engine/view retirement. Current protected recovery and the retained v1 offline facade have distinct formats. A state API query `page` is a bounded result resource, not a host memory page.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-protected-files](../latent-protected-files/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-commit](../latent-commit/README.md), [latent-effects](../latent-effects/README.md), [latent-workflows](../latent-workflows/README.md), [latent-wire](../latent-wire/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-state.lib.latent-state
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`promised_disposition_capacity_cannot_be_consumed_by_unrelated_writers`](src/embedded/tests.rs)
- [`reservation_generations_fence_stale_release_and_capacity_survives_reopen`](src/embedded/tests.rs)
- [`malformed_or_unsupported_reservations_never_publish_or_enable_readiness`](src/embedded/tests.rs)
- [`aggregate_reservations_charge_once_and_orphan_accounted_markers_refuse_every_writer`](src/embedded/tests.rs)

## Related documentation

- [State and effect architecture](../../docs/architecture/state-and-effects.md)
- [Shared state store ownership](../../docs/development/shared-state-store-owner.md)
- [Optimistic state sessions](../../docs/development/optimistic-state-sessions.md)
- [Atomic writer acceptance and coherent engine pages](../../docs/development/transaction-writer-fence.md)
- [Protected recovery and explicit resume](../../docs/architecture/protected-offline-recovery.md)
- [Namespace history and live version fences](../../docs/architecture/namespace-history-epochs.md)
- [Response retention and reserved storage recovery](../../docs/architecture/transaction-retention.md)
- [ADR-0063: Select redb for transactional host state](../../adr/0063-select-redb-for-transactional-host-state.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
