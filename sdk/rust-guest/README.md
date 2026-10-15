# latent-guest

Typed Rust capability and ownership helpers inside a WebAssembly component. Public guest APIs are `wasm32`-gated and use the authoritative shared generated bindings. The crate supplies no external client, executor, provider installation, grant, retry loop or ambient WASI access.

The `transaction` feature selects the separately admitted transaction guest ABI. Application WIT imports, exact profile selection and deployment policy must all match the host.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/bindings.rs](src/bindings.rs) | Exact maintained generated context/log/clock/events/metrics/random/service surfaces. |
| [src/http.rs](src/http.rs) | Bounded buffered request preserving typed uncertain failures. |
| [src/streaming.rs](src/streaming.rs) | Owned upload/body resources, explicit async operations and destructor-based abort. |
| [src/blob.rs](src/blob.rs) | Activation-owned reader/writer helpers with explicit asynchronous close/seal. |
| [src/secrets.rs](src/secrets.rs) | Borrowed access through one zeroizing guest byte owner. |
| [src/state.rs](src/state.rs) | Command/query/page borrowing and activation-bound state access; host owns commit. |
| [src/intents.rs](src/intents.rs) | Logical deferred intents staged only through an admitted command. |

## Execution and ownership

1. Build a maintained wasm32 component and map exact application imports to these shared generated resource types.
2. Host admission supplies the activation session and approved operations; a helper call cannot install or expand them.
3. Retain typed resource owners across async operations. Mutable state borrows prevent overlapping operations against the same command/query owner.
4. Explicitly close blob readers/writers or seal writes; async cleanup cannot be invented by Drop. Streaming destructors abort owned I/O, and secret Drop erases only its own guest allocation.

## Integration boundaries

Native compilation exposes no guest API and does not qualify actual Wasm linkage/execution. Store-local handles cannot survive activation retirement or become durable workflow state. Helpers preserve exact WIT errors and never retry uncertain operations. Host/provider authority, state commit and physical cleanup remain with their respective host owners.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Target-specific workspace edges:

| Target / dependency section | Package |
| --- | --- |
| `cfg(target_arch = "wasm32"):dependencies` | [latent-component-bindings](../../crates/latent-component-bindings/README.md) |

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | No additional feature dependency. |
| `transaction` | `latent-component-bindings/guest-transaction` |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-guest.lib.latent-guest
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Rust compiler and runtime profile](../../docs/component-development/rust-authoring.md)
- [Guest SDK capability reference](../../docs/component-development/guest-sdk.md)
- [Transactional aggregate guest](../../docs/component-development/transactional-authoring.md)
- [Standalone Rust capsule qualification](../../docs/development/rust-capsule-qualification.md)
- [Host ABI compatibility profiles](../../docs/runtime/host-abi-profile.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)

## Maintained example

The [blob fixture](../../tools/toolchain-smoke/examples/guest_blob/component.rs) demonstrates the asynchronous writer lifecycle:

```rust,ignore
let mut writer = latent_guest::blob::Writer::create("text/plain".into(), Some(4)).await?;
writer.write(0, b"data".to_vec()).await?;
let reference = writer.seal().await?;
```

Use the [pinned guest toolchain](../../tools/toolchain.toml) and the application bindgen `with` mappings from the maintained fixture; do not generate duplicate resource types.
