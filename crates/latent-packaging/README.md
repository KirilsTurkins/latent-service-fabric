# latent-packaging

Deterministic assembly and inspection of exact supplied package inputs. It validates package layout, capsule/WIT/component associations, supported host ABI and optional bounded SBOM inventory without compiling or invoking a guest.

Its observed-input build receipt records what packaging consumed and normalized. That receipt is not a compiler observation, publisher proof, builder approval or catalog admission grant.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/assembly.rs](src/assembly.rs) | Sorted layer assembly, canonical capsule metadata and exact input/output receipt identities. |
| [src/bundle.rs](src/bundle.rs) | PackageBundle inspection and digest/role/content association. |
| [src/directory.rs](src/directory.rs) | Descriptor-relative no-follow input access and manifest-last directory output. |
| [src/semantics/mod.rs](src/semantics/mod.rs) | Bounded WIT/component parsing and complete supported type/host contract checks. |
| [src/semantics/compatibility/invocation.rs](src/semantics/compatibility/invocation.rs) | Explicit opaque-payload service-call adapter compatibility, separate from a business function ABI. |
| [src/sbom.rs](src/sbom.rs) | Closed bounded CycloneDX inventory tied through package content. |
| [src/receipt.rs](src/receipt.rs) | BuildReceipt and per-input identities. |

## Execution and ownership

1. Accept explicitly supplied regular-file or in-memory inputs under PackagingLimits.
2. Bound input graphs before upstream parsers allocate or recurse; check WIT, component imports/exports and selected profile associations.
3. Canonicalize supported metadata, sort layers and build the exact config/manifest with a packaging input receipt.
4. Reinspect the resulting bundle. Signing, registry transfer and node admission then occur through their separate owners.

## Integration boundaries

Do not introduce hidden compilation, guest execution or ambient build commands here. Caller-approved root paths are explicit host authority; descendants remain capability-directory operations. Structural compatibility diagnostics do not grant service-call permission, and SBOM syntax/content validation does not prove a dependency is trustworthy.

## Dependencies and build

Direct workspace dependencies: [latent-artifacts](../latent-artifacts/README.md), [latent-core](../latent-core/README.md), [latent-contracts](../latent-contracts/README.md), [latent-manifest](../latent-manifest/README.md).

Consumers with normal workspace dependency edges include [latent](../../apps/latent/README.md), [latent-policy](../latent-policy/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-control-store](../latent-control-store/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-packaging.lib.latent-packaging
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`deterministic_role_separation_and_exact_received_identity`](src/sbom/tests.rs)
- [`duplicate_identity_and_conflicting_context_attribution_fail`](src/sbom/tests.rs)
- [`source_identity_rejects_paths_credentials_and_hidden_url_fields`](src/sbom/tests.rs)
- [`spdx_vocabulary_grammar_operators_and_complexity_are_validated`](src/sbom/tests.rs)

Integration targets: [tests/angular_build.rs](tests/angular_build.rs), [tests/compatibility.rs](tests/compatibility.rs), [tests/component_validation.rs](tests/component_validation.rs), [tests/directory.rs](tests/directory.rs), [tests/directory_evidence.rs](tests/directory_evidence.rs), [tests/host_abi.rs](tests/host_abi.rs), [tests/package_roundtrip.rs](tests/package_roundtrip.rs), [tests/sbom_association.rs](tests/sbom_association.rs).

## Related documentation

- [Contracts and bindings](../../docs/architecture/contracts-and-bindings.md)
- [Build observations and current builder trust](../../docs/reference/build-provenance.md)
- [Authenticated package admission](../../docs/reference/package-admission.md)
- [Creating a capsule](../../docs/component-development/creating-a-capsule.md)
- [ADR-0020: Validate supplied components without executing guests](../../adr/0020-validate-supplied-components-without-executing-guests.md)
- [ADR-0024: Bind SBOM inventory through package content](../../adr/0024-bind-sbom-inventory-through-package-content.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
