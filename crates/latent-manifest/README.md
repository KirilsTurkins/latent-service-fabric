# latent-manifest

Typed capsule, deployment, binding and trigger documents, bounded JSON codecs and semantic validation. The schemas define document syntax; the validator adds cross-field constraints, explicit execution profiles and runtime compatibility checks. Packaging, catalog publication and operator tools share this representation.

`Phase1ManifestValidator` is a retained API name, not a statement that every implemented document is limited to Phase 1. Conversely, an enum variant or `fusion_eligible` declaration does not install an execution backend or enable fusion.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Manifest models, execution requirements, resource declarations and public validation interfaces. |
| [src/codec.rs](src/codec.rs) | JSON document encoding/decoding and canonical document ownership. |
| [src/bounded_codec.rs](src/bounded_codec.rs) | Bounds checked before retaining parsed input. |
| [src/json_number.rs](src/json_number.rs) | Exact JSON number normalization rather than lossy floating-point identity. |
| [src/schema.rs](src/schema.rs) | Embedded authoritative schema validation without runtime filesystem discovery. |
| [src/validation.rs](src/validation.rs) | Cross-field semantic checks and supported-profile constraints. |
| [src/runtime_compatibility.rs](src/runtime_compatibility.rs) | Exact target, engine and CPU requirement descriptions. |
| [src/transaction_binding.rs](src/transaction_binding.rs) | Explicit transaction host binding and operation contract. |

## Execution and ownership

1. Decode bounded bytes as a selected document kind and reject ambiguous or structurally invalid input.
2. Apply schema and semantic checks using the explicitly selected validation profile; normalization preserves exact integer and digest meaning.
3. Pass checked metadata to packaging or the catalog. Runtime compatibility requirements remain constraints on the eventual host.
4. Admission and provider policy independently authorize execution; a valid manifest alone carries neither authority nor a live resource owner.

## Integration boundaries

Schema authority lives under `schemas/` at the repository root. Runtime host ABI recognition, signed package evidence and deployment policy have separate owners. Updating a supported requirement needs both codec/validation coverage and the implementing host profile; adding a manifest value alone cannot qualify a new runtime.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-packaging](../latent-packaging/README.md), [latent-policy](../latent-policy/README.md), [latent-routing](../latent-routing/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-manifest.lib.latent-manifest
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`canonicalizes_equivalent_non_integral_spellings`](src/json_number.rs)
- [`exponents_beyond_i128_are_exact_and_do_not_collapse`](src/json_number.rs)
- [`equality_and_ordering_remain_exact_at_exponent_boundaries`](src/json_number.rs)
- [`very_long_exponents_remain_compact_and_exact`](src/json_number.rs)

Integration targets: [tests/arbitrary_numbers.rs](tests/arbitrary_numbers.rs), [tests/canonical_decode_closure.rs](tests/canonical_decode_closure.rs), [tests/canonical_number_models.rs](tests/canonical_number_models.rs), [tests/canonical_payload_limits.rs](tests/canonical_payload_limits.rs), [tests/codec.rs](tests/codec.rs), [tests/deployment_normalization.rs](tests/deployment_normalization.rs), [tests/golden_fixtures.rs](tests/golden_fixtures.rs), [tests/integer_dialect.rs](tests/integer_dialect.rs), [tests/publication_selector.rs](tests/publication_selector.rs), [tests/robustness.rs](tests/robustness.rs), [tests/validation.rs](tests/validation.rs).

## Related documentation

- [Declarative resource schemas](../../schemas/README.md)
- [Manifest codec and admission contract](../../docs/protocol/manifest-codec.md)
- [Host ABI compatibility profiles](../../docs/runtime/host-abi-profile.md)
- [Contracts and bindings](../../docs/architecture/contracts-and-bindings.md)
- [Transaction host and original activation ownership](../../docs/development/phase4-runtime.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
