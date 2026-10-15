# latent-contracts

Structural contract descriptors and bounded compatibility/binding analysis. This crate describes application interfaces and compares supported value shapes without executing guest code. `BoundedBindingCompiler` supplies concrete checked binding behavior; `ContractRegistry` remains a storage port for another owner to implement.

Digests, documentation and equal names are insufficient compatibility evidence. The comparison examines supported ABI shapes and reports unsupported or unknown cases rather than inventing a conversion.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | ValueType, function/interface/contract descriptors, BindingPlan and registry/compiler ports. |
| [src/compatibility.rs](src/compatibility.rs) | Bounded directional structural comparison and explicit issues/work limits. |
| [src/binding.rs](src/binding.rs) | BoundedBindingCompiler and checked consumer/provider binding plans. |

## Execution and ownership

1. Receive complete bounded consumer/provider descriptors with exact contract identities.
2. Validate descriptor consistency and compare supported parameter/result/container shapes within explicit work limits.
3. Produce an exact checked binding plan or a typed incompatibility report. The comparison is directional, but compile_exact accepts only the supported identical ABI and creates no adapters or version substitution.
4. The catalog or broker associates that plan with current publication and policy owners before a call can start.

## Integration boundaries

Full WIT/component type inspection belongs to `latent-packaging`; this crate owns its deliberately smaller descriptor vocabulary. Registry persistence, route selection, provider installation and capability grants are separate. Unsupported resources, asynchronous shapes or unresolved named definitions must follow the comparison result rather than being assumed equivalent.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latent-artifacts](../latent-artifacts/README.md), [latent-packaging](../latent-packaging/README.md), [latent-control-store](../latent-control-store/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-contracts.lib.latent-contracts
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`exact_descriptors_use_the_abi_instead_of_digest_labels_or_documentation`](src/binding/tests.rs)
- [`unresolved_types_versions_dependencies_duplicates_and_limits_deny`](src/binding/tests.rs)
- [`scalar_and_complete_container_shapes_compare_without_trusting_digests`](src/compatibility/tests.rs)
- [`additions_removals_and_exact_versioned_identity_are_directional`](src/compatibility/tests.rs)

## Related documentation

- [Contracts and bindings](../../docs/architecture/contracts-and-bindings.md)
- [WIT value payloads](../../docs/protocol/wit-values.md)
- [Exact capability bindings](../../docs/runtime/capability-bindings.md)
- [ADR-0003: Use WIT as the capsule contract authority](../../adr/0003-use-wit-as-the-capsule-contract-authority.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
