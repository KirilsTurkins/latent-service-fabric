# latent-toolchain-smoke

Compile probes and maintained component fixtures for the pinned build foundation. Native library probes exercise selected dependency APIs; wasm32 examples export real WIT interfaces used by runtime/provider tests. The two roles must not be confused with running a production node.

The library does not construct an engine, Store, listener or service runtime. Explicit helper calls such as temporary-directory creation still own their individual resources.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Target-gated dependency probes and shared generated runtime bindings. |
| [Cargo.toml](Cargo.toml) | Explicit cdylib example targets and their host/guest dependency split. |
| [examples/echo_capsule/component.rs](examples/echo_capsule/component.rs) | Maintained echo component and application behavior. |
| [examples/containment_capsule/component.rs](examples/containment_capsule/component.rs) | Execution limit/failure fixture. |
| [examples/guest_http/component.rs](examples/guest_http/component.rs) | Typed production guest SDK HTTP fixture. |
| [examples/guest_blob/component.rs](examples/guest_blob/component.rs) | Owned blob create/write/seal/read/close fixture. |
| [examples/optimization_capsule/component.rs](examples/optimization_capsule/component.rs) | Wasm arm using the exact shared deterministic workload logic. |
| [tests/echo_capsule.rs](tests/echo_capsule.rs) | Finite source-level echo behavior checks. |

## Execution and ownership

1. Select the pinned toolchain and the registered suite/recipe that owns the desired fixture.
2. Compile host probes and selected wasm32 examples through the declared target graph.
3. The preparation recipe builds/packages fixture bytes before runtime test discovery.
4. Concrete runtime tests consume those exact fixtures to establish linkage, execution, provider behavior and cleanup at their own boundary.

## Integration boundaries

A compile-only probe is not a security/performance qualification run. Examples marked test=false are not automatically built into every lib test; use the registered fixture owner. Do not hand-edit generated WIT Rust or bypass preparation with an arbitrary Cargo test command and assume artifacts are current.

## Dependencies and build

Direct workspace dependencies: [latent-component-bindings](../../crates/latent-component-bindings/README.md), [latent-optimization-workloads](../optimization-workloads/README.md).

Target-specific workspace edges:

| Target / dependency section | Package |
| --- | --- |
| `cfg(target_arch = "wasm32"):dependencies` | [latent-guest](../../sdk/rust-guest/README.md) |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-toolchain-smoke.lib.latent-toolchain-smoke
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`echoes_normal_input_without_modification`](tests/echo_capsule.rs)
- [`rejects_an_empty_message`](tests/echo_capsule.rs)
- [`accepts_the_documented_byte_limit`](tests/echo_capsule.rs)
- [`rejects_a_message_over_the_documented_byte_limit`](tests/echo_capsule.rs)

Integration targets: [tests/echo_capsule.rs](tests/echo_capsule.rs).

## Related documentation

- [Executable build foundation](../../docs/development/build-foundation.md)
- [Toolchain and reproducibility baseline](../../docs/development/toolchain.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Prepared AOT test inputs](../../docs/development/aot-test-inputs.md)
- [Guest SDK capability reference](../../docs/component-development/guest-sdk.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
