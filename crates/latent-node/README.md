# latent-node

Local activation lifecycle orchestration and activation-scoped transaction integration. `LocalActivationManager` composes the pinned catalog, admission, scheduler, artifact repository and execution backend, while owning cancellation, retained journal status, accounting and terminal cleanup. It is the normal entry point for both external invocations and local child calls.

The crate does not open network listeners or bootstrap provider credentials. The application composition root supplies those shared services and the actual protected storage/authority owners.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/activation_manager/mod.rs](src/activation_manager/mod.rs) | Manager dependencies, accepted ActivationHandle and one lifecycle owner. |
| [src/activation_manager/run.rs](src/activation_manager/run.rs) | Resolution/admission/scheduling/preparation/execution and explicit cell disposition. |
| [src/activation_manager/local_service.rs](src/activation_manager/local_service.rs) | Separate child activation lifecycle and original parent ownership. |
| [src/cancellation.rs](src/cancellation.rs) | Cancellation registration/token ownership and bounded reasons. |
| [src/journal.rs](src/journal.rs) | Finite retained activation status, trees, paging and terminal summaries. |
| [src/budgeted_activation.rs](src/budgeted_activation.rs) | Original activation ledger installation and finalization. |
| [src/transaction_runtime/mod.rs](src/transaction_runtime/mod.rs) | Native state host, affine snapshots/staging and physical retirement. |
| [src/command_waiters.rs](src/command_waiters.rs) | Finite delivery notifications; durable command/result authority stays in the commit/store owners. |
| [src/inventory.rs](src/inventory.rs) | Bounded node topology, resource and lifecycle observations. |

## Execution and ownership

1. Validate trusted inbound context and accept one activation identity/journal/cancellation owner.
2. Pin a coherent catalog, resolve and admit under the original deadline. Ordinary requests prepare immutable readiness while retaining quota, before acquiring a fair fixed-cell assignment; nested calls reserve their existing child cell first.
3. Materialize the retained readiness/imports after assignment, attach original budget/cancellation and optional transaction host, and invoke the backend. Transaction input canonicalization may require earlier readiness before command admission.
4. Translate returned/declared/trap/interruption outcomes, complete the transaction when selected and retire backend/native resources.
5. Release or quarantine the cell, finalize consumption and publish retained terminal status. The same lifecycle guard handles abandonment and panic.

## Integration boundaries

A local service call creates a fresh child Store, principal, admission and accounting delegation; it is not inline fusion. A waiting parent retains its cell. Transport waiter drop, explicit cancellation, deadline and durable transaction disposition must not be collapsed into one abort claim. `Phase0ActivationRunner` is a compatibility facade. `transaction-test-observation` exposes controlled observations rather than another production state path.

## Dependencies and build

Direct workspace dependencies: [latent-activation](../latent-activation/README.md), [latent-admission](../latent-admission/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-commit](../latent-commit/README.md), [latent-core](../latent-core/README.md), [latent-executor](../latent-executor/README.md), [latent-effects](../latent-effects/README.md), [latent-manifest](../latent-manifest/README.md), [latent-policy](../latent-policy/README.md), [latent-routing](../latent-routing/README.md), [latent-scheduler](../latent-scheduler/README.md), [latent-state](../latent-state/README.md), [latent-telemetry](../latent-telemetry/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-nats](../latent-nats/README.md), [latent-wire](../latent-wire/README.md), [latent-control-store](../latent-control-store/README.md), [latent-testkit](../latent-testkit/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `transaction-test-observation` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-node.lib.latent-node
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`system_deadline_owns_one_sleep_and_never_completes_before_expiry`](src/activation_manager/control/tests.rs)
- [`injected_clock_rechecks_with_bounded_sleeps_until_its_own_expiry`](src/activation_manager/control/tests.rs)
- [`absent_and_already_expired_deadlines_never_arm_a_sleep`](src/activation_manager/control/tests.rs)
- [`dropping_a_pending_wait_refunds_its_only_live_guard`](src/activation_manager/control/tests.rs)

Integration targets: [tests/activation_lifecycle.rs](tests/activation_lifecycle.rs), [tests/activation_runner.rs](tests/activation_runner.rs), [tests/activation_runner_races.rs](tests/activation_runner_races.rs), [tests/scheduling_cancellation.rs](tests/scheduling_cancellation.rs).

## Related documentation

- [Data-plane architecture](../../docs/architecture/data-plane.md)
- [Activation lifecycle protocol](../../docs/protocol/activation-lifecycle.md)
- [Isolated local service invocation](../../docs/runtime/local-service-invocation.md)
- [Budgets and cancellation trees](../../docs/runtime/descendant-budgets.md)
- [Transaction host and original activation ownership](../../docs/development/phase4-runtime.md)
- [Bounded command delivery notifications](../../docs/development/command-delivery-notifications.md)
- [Phase 0 activation containment](../../docs/development/activation-containment.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
