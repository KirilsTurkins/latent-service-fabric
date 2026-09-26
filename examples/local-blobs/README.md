# Local immutable blob guest fixture

[blob-probe.wit](wit/blob-probe.wit) defines a small async guest using the exact
`latent:blob/blob@0.2.0` interface. The executable component is encoded by the
[conformance fixture](../../crates/latent-wasmtime/tests/local_blobs/component.rs)
and runs against the real broker, policy owner, Linux blob store and Wasmtime
adapter. Generated host/guest bindings derive from the same authoritative WIT.

Run `cargo test -p latent-wasmtime --test local_blobs --locked` on Linux. No
external storage service, load campaign or persistent deployment is required.

The normal mode writes eight bytes in two chunks, seals, opens, reads the second
range, materializes it once and drops the resource. It returns `4101`. Additional
modes exercise an empty value, stale/cross-activation handles, wrong-kind reads,
trap cleanup and invalid resources. The value protocol encodes `u64` arguments
and results as decimal strings; for example the ordinary arguments are
`[0,"0"]` and the result is `["4101"]`.

The embedding explicitly configures its private root, limits and provider plan.
No guest path or digest grants filesystem authority. See the complete
[storage, ownership and durability contract](../../docs/runtime/local-blobs.md).
