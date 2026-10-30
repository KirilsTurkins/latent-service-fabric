# Selected WASI HTTP guest runtime

This compiler-owned adapter lets the selected Rust WASI HTTP application path
use ordinary WASI 0.2.12 HTTP/I/O interfaces over LSF's typed streaming HTTP,
activation and monotonic-clock imports. It is guest code composed into a capsule,
not an ambient host WASI installation or a general socket provider.

The [Rust WASI HTTP guide](../../docs/testing/rust-wasi-http-runtime.md) records
the finite ordinary-client programmes, their original native/component identities
and remaining qualification. Installing or compiling an adapter grants no HTTP
authority and does not qualify a different current host.

## Source and composition

The [actual component entry point](../../tools/toolchain-smoke/examples/rust_wasi_http_runtime.rs)
generates bindings from [the client world](wit/world.wit) and includes these
modules. This directory is not an independent Cargo workspace.

| Source | Responsibility |
| --- | --- |
| [types.rs](types.rs), [fields.rs](fields.rs) | Typed HTTP resources, methods and bounded header fields. |
| [state.rs](state.rs) | One owned exchange: upload, response, body, EOF, drain, trailers and retained results. |
| [io.rs](io.rs) | Standard stream operations and views over that exchange. |
| [poll.rs](poll.rs) | Pollable readiness and timers using the shared activation pump. |
| [request_options.rs](request_options.rs) | Selected request phase/deadline options; no replacement root deadline. |
| [error.rs](error.rs) | Bounded resources preserving typed host failure categories. |
| [limits.rs](limits.rs) | The selected profile's chunk, body and header bounds. |
| [wit/](wit) | Exact exported standard interfaces and imported LSF authority. |

The adapter reuses the original .NET HTTP runtime's
[Owner](../dotnet-guest/runtime/http/owner.rs),
[Pump](../dotnet-guest/runtime/http/pump.rs),
[quota](../dotnet-guest/runtime/http/quota.rs) and
[timer](../dotnet-guest/runtime/http/timer.rs) sources. Each selected component has
one instance of those owners; this does not introduce another provider, budget,
executor or connection cache. Futures, resources and buffers retain their original
owners through actual retirement. EOF and trailer observation remain explicit;
dropping a result waiter is not proof that pending work stopped.

## Producer and consumer identities

[rust_wasi_http_inputs.py](../../tools/rust_wasi_http_inputs.py) binds the adapter
source closure, shared owners, pinned tools and emitted component products.
[rust_wasi_http_profile.py](../../tools/rust_wasi_http_profile.py) checks the
selected interface graph. Consumer forwarding, projection and composition are
bound separately from producer inputs, so changing a consumer cannot relabel an
old adapter build. A new README in this captured directory also changes its
source inventory; old receipts keep their original identity.

The internal projection marks exactly eight blocking I/O declarations async;
it does not change public application export contracts. The adapter's clock
resolution operation explicitly refuses unsupported precision rather than
inventing a value. HTTP grants remain method/path/header grants, not permission
for arbitrary socket bytes, DNS or TLS APIs.

## Upstream and verification

[upstream-source.json](upstream-source.json) authenticates the original
`wasip2 1.0.4+wasi-0.2.12` archive, selected files and the separately identified
I/O projection. The copied manifests and interfaces are provenance inputs, not
a second package to build here. The exact upstream
[Apache-2.0](upstream/LICENSE-APACHE) and [MIT](upstream/LICENSE-MIT) license texts
remain alongside them; see also [NOTICE](../../NOTICE).

Use the guide's owning qualification workflow and
[installed recipe](../../tools/qualify_rust_wasi_http_installed.py) for genuine
component/node evidence. Native source controls, a successful adapter build and
a signed application programme establish different boundaries. General
`std::thread`, arbitrary executors, standard raw sockets and durable continuation
restoration are outside this adapter's contract.
