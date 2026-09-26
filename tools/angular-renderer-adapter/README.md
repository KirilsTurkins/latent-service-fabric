# Angular renderer adapter

This fixed guest adapter composes the closed JavaScript renderer with the public
async `latent:web/application@0.1.0` interface. It uses the node's generic Wasmtime
backend and a fresh Store for every render. The private synchronous `engine`
interface must be satisfied inside the final component.

`runtime/timers.js` installs cumulative 256 zero-delay timer and 4096 explicit
microtask bounds before application modules evaluate. Native Promise work also
requires the runtime's fuel, epoch, memory and cancellation bounds. Guest-instance
reuse is rejected. No node-side JavaScript event loop or application worker is
created.

The Rust adapter samples principal, activation lineage, trace and deadline from
host context. The private request frame has a 256 KiB ceiling; results have a
1 MiB encoded-frame and 128 KiB HTML ceiling. HTTP header and delivery validation
remain part of the shared HTTP boundary. Public response bodies use canonical
base64; HEAD and 304 describe the representation without returning its body.

The `abi` module contains only generated WIT bindings and their canonical export.
It is the sole unsafe-code allowance; handwritten guest code is denied unsafe
operations. Build with the pinned Rust toolchain for `wasm32-unknown-unknown`.

The [runtime fixture](../../examples/renderer-profile/componentize-runtime.mjs)
uses the maintained Angular build and adversarial application routes to exercise
the actual adapter. This fixture does not authorize arbitrary build commands or
replace observed application packaging.
