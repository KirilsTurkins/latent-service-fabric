# Streaming HTTP resource probe

This maintained canonical async component imports
`latent:http/streaming@0.3.0` and exports `tests:streaming-http/api@1.0.0`.
The [WIT world](wit/streaming-probe.wit) is frozen with the package built by
[the conformance fixture](../../crates/latent-wasmtime/tests/streaming_http/packages.rs).
The [component encoder](../../crates/latent-wasmtime/tests/streaming_http/component.rs)
constructs actual own/borrow/drop and async canonical operations from that WIT.
No prebuilt binary or generated benchmark report is committed.

The normal modes upload eight bytes in two chunks, then either return after the
first response chunk (`which = 0`) or drain the body and trailers (`which = 2`).
Other fixture modes exercise traps, explicit abort, invalid handles, wrong
resource types and stale Drop. Repeated chunk/trailer materialization must fail.
Each invocation uses a fresh Store and the same reusable execution cell.

Run the real TCP/guest conformance tests on Linux:

```bash
cargo test -p latent-wasmtime --test streaming_http --locked
cargo test -p latent-http --lib --locked
```

The fixture explicitly authorizes its loopback peer. Applications require their
own installed provider and exact tenant/publication/revision grant. The
[streaming profile](../../docs/runtime/streaming-http.md) documents configuration,
transfer/window limits, original deadlines, verified EOF and uncertainty.
