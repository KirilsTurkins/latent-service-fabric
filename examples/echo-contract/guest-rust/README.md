# Rust echo capsule fixture

This directory contains the handwritten Rust implementation of the checked-in
[`examples:echo/service@0.1.0`](../wit/echo.wit) world. The Cargo target is declared
by `tools/toolchain-smoke/Cargo.toml` as the `echo-capsule` `cdylib` example so the
fixture reuses the Phase 0 lock graph instead of introducing an independently
resolved guest workspace.

The component uses bindings generated from the authoritative WIT sources. It does
not define ABI structs, discriminants, import names, or export names by hand.

## Behavior

`echo(message)` measures the UTF-8 input in bytes:

- `1..=4096` bytes return the original string unchanged;
- zero bytes return `empty-message`;
- more than 4096 bytes return `message-too-large`.

Every invocation reads `latent:context/context.activation-id` and makes exactly one
best-effort `latent:log/log.write` call at `info` level. The log message is the
constant `echo invocation`; fields are limited to `activation.id`, `message.bytes`,
and `outcome`. The activation ID is truncated at a UTF-8 boundary to at most 128
bytes, and user message contents are never logged. A declared logging error does
not replace the echo contract's result.

The guest starts no thread, process, runtime, listener, socket, service, or
execution cell. It receives only the two capabilities declared by the WIT world.

## Build and validation

From the repository root, with the pinned tools installed:

```bash
make echo-capsule
```

The command writes a local-only bundle below `target/capsules/echo-rust/`:

```text
echo.component.wasm
component.wit
capsule.json
digest.txt
build-metadata.json
local-trust.json
```

The generated capsule manifest contains the SHA-256 digest of the exact component
bytes. `local-trust.json` explicitly limits trust to the Phase 0 development
fixture; no signature or production provenance is claimed.

The full acceptance check performs two clean builds, requires byte-for-byte
identity, validates inferred WIT with `wasm-tools`, and invokes normal, empty, and
oversized inputs through generated Wasmtime bindings:

```bash
make echo-capsule-check
```

Reproducibility is defined for repeated clean builds from the same source tree
using the committed `Cargo.lock`, Rust 1.97.1, `wasm32-wasip2`, release profile,
a fixed clean Cargo target path, repository-path remapping, and the selected
`wasm-tools` version. Cross-host identity is not claimed by this
Phase 0 fixture.
