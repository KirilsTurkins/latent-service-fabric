# Standard outbound contract comparison

This work belongs to [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737)
and [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md), separate from
the immutable [#696 investigation](../outbound-streams/README.md).
The [finite profile](../../docs/runtime/outbound-stream-profile.md) proposes
standard runtime networking beneath unchanged dependencies. Production remains
disabled until review and implementation-backed qualification.

Parse/encode the exact comparison WIT with the pinned `wasm-tools`:

```powershell
New-Item -ItemType Directory -Force target/outbound-contract | Out-Null
wasm-tools component wit research/standard-outbound --wasm --output target/outbound-contract/profile.wasm
wasm-tools validate --features all target/outbound-contract/profile.wasm
```

The generated type-only component is ABI evidence, not executing library/socket
evidence. The `outbound_proposal_and_wasi_sockets_are_not_ambient_authority`
case in `crates/latent-wasmtime/tests/generic_backend/host_abi.rs` separately uses a
real component to verify that unknown standard WASI socket imports cannot acquire
authority through the current host. Positive provider evidence belongs to #738.
All-six ordinary library execution belongs to the language ports and #740/#694.
