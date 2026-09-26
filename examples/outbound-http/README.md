# Outbound HTTP probe capsule

This maintained example imports `latent:http/client@0.2.0` and exports
`tests:http/api@1.0.0`. Its [WIT](wit/http-probe.wit) remains the source contract.
The [component generator](../../crates/latent-wasmtime/tests/http/component.rs)
builds an actual async Component Model guest; the
[package builder](../../crates/latent-wasmtime/tests/http/packages.rs) validates
its manifest, contracts, WIT lock and component surface together.

The `run(which)` operation selects GET, HEAD, POST, PUT, PATCH, DELETE or OPTIONS
with values 0 through 6. The test supplies a loopback URL and a seven-byte body.
The guest returns `status + 1000 * response_body_length`, or `1000 + error_index`
for the frozen HTTP error variant. Test mode 8 deliberately traps after receiving
the response to verify real resource reclamation.

Run the capsule against the real provider and production Wasmtime backend on Linux:

```sh
cargo test -p latent-wasmtime --test http --locked
```

The harness creates temporary catalog publications, a configured shared provider,
exact policy/binding records and a Phase 3 activation ledger. It verifies all seven
methods, canonical response lowering, package compatibility, repeated warm-cell
execution, cancellation, traps, denied paths and revoked plans. Temporary fixtures
are small and removed at test completion; no benchmark reports or stored private
keys are generated.

See the [provider profile](../../docs/runtime/outbound-http.md) for trusted
embedding configuration and its bounds. Standalone provider configuration belongs
to #226; this example does not imply that a default `latentd serve` grants egress.
The language guest binding deliverables remain part of #221.
