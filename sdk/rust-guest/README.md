# Rust guest SDK

`latent-guest` provides typed capabilities inside a WebAssembly component.
Its API is available on `wasm32`, uses the authoritative generated
`latent-component-bindings` profile, and adds no executor, provider, grant or
retry policy. The external Rust client interfaces live in `../rust`.

Start with [the standalone project guide](../../docs/component-development/rust-authoring.md)
to create, build, sign, deploy and invoke an independently editable application.

Use Rust 1.97.1, `wit-bindgen` 0.62.0, `wasm32-unknown-unknown`, and
`wasm-tools` 1.254.0 as pinned in `tools/toolchain.toml`. The maintained examples
map each exact application WIT import to `latent_guest::bindings` in their
`wit_bindgen::generate!` configuration. This keeps imported resource types
identical to the SDK's types. WIT and deployment policy must both permit a call.

For example, the maintained [blob guest](../../tools/toolchain-smoke/examples/guest_blob/component.rs)
uses an owned writer:

```rust,ignore
let mut writer = latent_guest::blob::Writer::create("text/plain".into(), Some(4)).await?;
writer.write(0, b"data".to_vec()).await?;
let reference = writer.seal().await?;
```

HTTP, streaming and blob helpers preserve the generated typed errors. Secret
bytes have one zeroizing owner with borrowed access. Events, service calls,
random and metrics expose the authoritative typed operations directly.
Dropping a pending operation is not evidence that an external effect did not
happen. Neither helpers nor examples retry uncertain outcomes.

The [guest SDK reference](../../docs/component-development/guest-sdk.md) gives
the build, signed admission and execution workflow, exact host ABI table,
least-privilege policies and close/drop rules. The native build of this crate
has no guest API and does not prove guest conformance; the contract CI job
compiles and executes the real Wasm fixtures.
