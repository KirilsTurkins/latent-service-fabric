# latent-component-bindings

Single build-generated Rust binding owner for LSF's authoritative WIT worlds. Native consumers receive Wasmtime host bindings; `wasm32` consumers receive guest bindings. Sharing generated resource identities prevents handwritten host and guest adapters from drifting apart.

This package generates types and bindings. Linking it does not create an Engine, Store, scheduler, listener or provider. Generated Rust belongs in Cargo `OUT_DIR`, while the checked-in WIT remains the interface authority.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [build.rs](build.rs) | Selects authoritative WIT worlds and emits host/guest bindings into OUT_DIR. |
| [src/lib.rs](src/lib.rs) | Target-gated generated modules, supported ABI profiles and mutually exclusive capsule guest selections. |

## Execution and ownership

1. Cargo runs the build script against checked-in WIT inputs and the pinned generators.
2. Native builds expose activation, web, runtime, Phase 3, streaming, blob, transaction and fixture host surfaces as selected by the source.
3. Wasm builds expose maintained guest surfaces. `guest-activation` and `guest-transaction` select incompatible capsule profiles and cannot both be enabled on wasm32.
4. A runtime or SDK implements and installs the generated interfaces; generated signatures themselves grant no host authority.

## Integration boundaries

Do not edit emitted Rust or add a second local binding generator to repair a type mismatch. Update the authoritative WIT and this build owner, then qualify each affected runtime/SDK surface. A successful native compile is not evidence that a guest component links or executes.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Consumers with normal workspace dependency edges include [latent-wasmtime](../latent-wasmtime/README.md), [latent-toolchain-smoke](../../tools/toolchain-smoke/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | No additional feature dependency. |
| `guest-activation` | No additional feature dependency. |
| `guest-transaction` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-component-bindings.lib.latent-component-bindings
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [WIT contracts](../../wit/README.md)
- [Executable build foundation](../../docs/development/build-foundation.md)
- [Host ABI compatibility profiles](../../docs/runtime/host-abi-profile.md)
- [Guest SDK capability reference](../../docs/component-development/guest-sdk.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
