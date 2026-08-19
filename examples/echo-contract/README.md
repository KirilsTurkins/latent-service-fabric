# Phase 0 Rust echo capsule fixture

The authoritative contract remains [`wit/echo.wit`](wit/echo.wit). The Rust guest implementation is the `echo-capsule` example target in [`../../tools/toolchain-smoke/examples/echo_capsule/component.rs`](../../tools/toolchain-smoke/examples/echo_capsule/component.rs). `wit-bindgen` generates every guest import, export trait, canonical ABI shim, and domain-error type directly from the checked-in WIT packages.

## Behavior

The fixture applies a documented limit of **65,536 UTF-8 bytes** to the message.

- A non-empty message at or below the limit is returned byte-for-byte.
- An empty message returns `empty-message`.
- A message larger than the limit returns `message-too-large`.

Every invocation reads `activation-id` through `latent:context/context@0.1.0` and makes exactly one best-effort call to `latent:log/log@0.1.0`. The log has a constant message and three fields: a UTF-8-safe activation ID prefix capped at 128 bytes, the decimal input byte count, and a fixed outcome label. A log rejection never replaces the declared echo result.

## Build and validation

Install the pinned tools from [`../../docs/development/toolchain.md`](../../docs/development/toolchain.md), then run:

```bash
make echo-capsule
```

The direct command is:

```bash
python3 tools/build_echo_capsule.py
```

A reproducibility check performs two isolated clean builds and requires byte-identical component bytes:

```bash
make echo-capsule-reproducibility
```

The generated output is written beneath `target/capsules/echo/` and is intentionally ignored by Git:

```text
echo-capsule.wasm       validated Component Model artifact
capsule.json             capsule metadata with the computed SHA-256 digest
build.json               stable toolchain, interface, trust, and reproducibility receipt
sha256.txt               content digest for the spike runner
interface.json           machine-readable interface extracted by wasm-tools
interface/               extracted root world and dependency WIT packages
```

`wasm-tools validate` must accept the component. The extracted root world must have exactly these imports and export, with no ambient WASI capabilities:

```wit
world root {
    import latent:context/context@0.1.0;
    import latent:log/log@0.1.0;
    export examples:echo/api@0.1.0;
}
```

The extracted exported interface is also checked for `echo`, `empty-message`, and `message-too-large`.

## Trust and reproducibility boundary

The artifact is locally trusted because it is produced from the current checkout with the committed `Cargo.lock`, Rust 1.97.1, `wasm32-wasip2`, `wit-bindgen` 0.60.0, and `wasm-tools` 1.254.0. It is not signed and is not an OCI artifact. `capsule.json` and `build.json` state this explicitly.

The verified reproducibility claim is byte identity for two clean builds from the same checkout and source path on the same host platform with the pinned toolchain, target, lockfile, and canonical release settings. Cross-platform byte identity is not claimed by Phase 0.

Building compiles and validates files only. It does not start a service process, open a listener, create a runtime instance, lease an execution cell, or reserve any capsule-owned idle resource.
