# latent-core

Shared identity, error, lifecycle, time and resource-ownership vocabulary for the workspace. This is the lowest runtime foundation: higher layers use its typed digests and IDs to distinguish content, publication, activation and transaction identities. It also implements checked activation/descendant accounting and Store-local logical scheduling owners; it is more than a collection of serializable DTOs.

The crate has no workspace dependencies. It does not create a node, open a database, authenticate a request or install a provider. Its clocks, ledgers and logical runtime registries are explicitly constructed by their owning host.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/digest.rs](src/digest.rs) | Typed component/package/blob digest domains and canonical parsing; equal-looking strings do not erase identity domains. |
| [src/budget.rs](src/budget.rs) | Activation ledger, consumption, reservations and descendant delegation; physical owners control refundable capacity. |
| [src/clock.rs](src/clock.rs) | Wall/monotonic samples and injectable activation clocks. |
| [src/activation_runtime.rs](src/activation_runtime.rs) | Finite Store-generation task, continuation and timer ownership; invocation-local scheduling, not durable workflow capture. |
| [src/native_capacity.rs](src/native_capacity.rs) | Original shared native-capacity ownership and observations. |
| [src/host_profile.rs](src/host_profile.rs) | Versioned host ABI recognition, independent of installed provider and policy authority. |
| [src/transaction_contract.rs](src/transaction_contract.rs) | Shared command/query identity and bounded transaction contract values. |

## Execution and ownership

1. Adapters validate external values into the appropriate ID, digest, principal and error domains before higher layers use them.
2. Admission supplies the effective budget and original deadline. Resource owners reserve against that ledger before retaining work or bytes.
3. Child delegation preserves the original parent accounting owner and deadline. A descriptive budget copy cannot create additional spendable capacity.
4. Owners release reservations at actual reclamation. Store-local scheduling handles cease to be usable outside their original generation.

A supplied continuation token must identify a still-live owner in the same
Store generation even before root closing. Invalid ancestry fails before record
allocation or work admission; omitting a continuation still requests independent
work under the normal lifecycle rules.

## Integration boundaries

Use `test-support` only for deterministic clocks, IDs, workspaces and coordination helpers. Upstream foundations can depend on that feature directly without pulling in the node-dependent test harness. Declared application errors and platform failures remain separate types. Diagnostic observations describe owners; they do not mint permission or prove that native work stopped.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-manifest](../latent-manifest/README.md), [latent-contracts](../latent-contracts/README.md), [latent-rpc](../latent-rpc/README.md), [latent-artifacts](../latent-artifacts/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `test-support` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-core.lib.latent-core
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`lazy_path_allocates_no_records_and_accepted_owners_share_finite_limits`](src/activation_runtime/tests.rs)
- [`close_allows_bounded_live_continuations_and_rejects_independent_work`](src/activation_runtime/tests.rs)
- [`waking_a_parked_thread_leaves_runnable_sibling_and_fences_reused_slots`](src/activation_runtime/tests.rs)
- [`foreign_store_token_and_opaque_sleeping_work_cannot_establish_quiescence`](src/activation_runtime/tests.rs)

## Related documentation

- [Resource budgets, deadlines, and cancellation](../../docs/runtime/resource-budgets.md)
- [Budgets and cancellation trees](../../docs/runtime/descendant-budgets.md)
- [Activation-owned runtime support](../../docs/runtime/activation-runtime.md)
- [Platform error model](../../docs/protocol/platform-errors.md)
- [Native admission and recovery capacity](../../docs/development/native-admission-capacity.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
