# latent-executor

Engine-independent preparation, execution and cleanup contracts. The node uses `ExecutionBackend` to acquire immutable prepared code, materialize activation-specific ownership, execute with cancellation/budget context and receive an explicit cleanup disposition.

This crate defines no Wasmtime engine or native guest loader. Its owned preparation wrappers are important: an opaque descriptor is not a substitute for the original code pin, capacity reservation or transaction host owner.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | ExecutionBackend, preparation/cell descriptors, cancellation ports, GuestOutcome and ExecutionReport. |
| [src/prepared_readiness.rs](src/prepared_readiness.rs) | Immutable readiness pin acquired before ordinary execution-cell assignment and retained across materialization. |
| [src/prepared_use.rs](src/prepared_use.rs) | Typed ownership behind a prepared descriptor; failed downcasts preserve ownership. |
| [src/prepared_activation.rs](src/prepared_activation.rs) | Activation-specific preparation/import ownership. |
| [src/preparation_read_wait.rs](src/preparation_read_wait.rs) | Bounded currentness-read wait port; not a generic replay mechanism. |
| [src/transaction.rs](src/transaction.rs) | Admitted transaction host, scope, values and activation-local state resources. |

## Execution and ownership

1. Prepare exact artifact/runtime identities without retaining mutable guest activation state in a cache.
2. Carry the original readiness and prepared-use owner into materialization and execution.
3. Execute under the activation cancellation probe, original deadline, budget ledger and optional already-admitted transaction host.
4. Return success, declared error, trap or interruption independently of cleanup. Only `Reusable` permits reuse; incomplete cleanup reports quarantine.

## Integration boundaries

A timeout observed by a waiter is not proof that execution stopped. Default wait adapters delegate once and preserve the original future rather than retrying work. There is no durable suspended outcome or compiler continuation capture here; those remain research proposals. Implementing the trait alone does not qualify a new backend's admission, ABI or cleanup boundary.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md), [latent-artifacts](../latent-artifacts/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-wire](../latent-wire/README.md), [latent-node](../latent-node/README.md), [latent-testkit](../latent-testkit/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-executor.lib.latent-executor
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`budget_dimensions_have_deterministic_interruption_mappings`](src/lib.rs)
- [`default_wait_api_delegates_once_without_consulting_timer_or_replaying_failure`](src/preparation_read_wait/tests.rs)
- [`default_wait_api_preserves_unpolled_and_pending_future_ownership`](src/preparation_read_wait/tests.rs)
- [`default_materialization_wait_delegates_once_without_timer_or_replaying_failure`](src/preparation_read_wait/tests.rs)

## Related documentation

- [Data-plane architecture](../../docs/architecture/data-plane.md)
- [Execution-cell architecture](../../docs/architecture/execution-cells.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Bounded asynchronous host I/O](../../docs/runtime/async-host-io.md)
- [Continuation-eviction research](../../docs/runtime/continuation-eviction-research.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
