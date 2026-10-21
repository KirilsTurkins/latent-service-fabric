# Selected Rust WASI HTTP runtime

This source implements a selected backend for the six external WASI 0.2.12
interfaces observed from ordinary, unchanged Waki and Golem clients. Its first
owning workflow compiles the adapter and exercises bounded fields/options
controls. **The adapter and compiler integration have not yet passed a signed
client programme.** Compilation alone does not qualify #689 or #743.

The upstream files are complete originals from
[`wasip2 1.0.4+wasi-0.2.12`](https://crates.io/crates/wasip2/1.0.4+wasi-0.2.12).
`sdk/wasi-http-runtime/upstream-source.json` records the exact archive checksum,
original file hashes, manifests and both licenses. The complete original I/O
WIT is preserved under `upstream/wit/deps/io.wit`; the active owned copy changes
exactly eight internal blocking declarations to async, matching their actual
Rust bindings. Every other byte must remain identical. Unused filesystem/socket
definitions remain source dependencies; the selected world exports only HTTP,
I/O and monotonic-clock interfaces. It imports only the existing typed HTTP,
activation runtime and monotonic clock. It installs no provider or grant.

The backend shares the original .NET Pump, Owner, Timer and 64-slot quota,
with one instance and ledger in the selected component. Original .NET runtime
source files remain unchanged. The separate Rust exchange preserves its
original preimage and adds verified EOF, unread-body drain and actual typed
trailers. The original chunk/body/header limits remain mandatory.

The selected surface preserves field bytes, duplicates and child lifetimes;
non-UTF-8 fields are concretely refused at the typed host boundary. Reserved
credentials/framing are still checked by the original provider. Request-options
resources implement actual defaults and `None` setters; nondefault phase
timeouts return an error. Server response construction and unauthenticated
clock-resolution reporting trap explicitly. No server, ambient socket, executor
or thread implementation is claimed. Requested timeout features, pooling,
library middleware and TLS customization need their own supported semantics and
qualification; this backend never reconnects or replays a request.

An explicit installation on Linux x86-64 runs one locked, offline Wasm adapter
compile after its SDK compiler dependencies are acquired:

```sh
python3 -B tools/rust_wasi_http_inputs.py --output /absolute/owned/http-runtime
```

The original receipt binds compiler/tool identities, whole producer source,
component/core bytes and the complete actual WIT graph. Producer source excludes
the unexecuted root/composition helpers; a consumer recipe separately binds
those exact current files. The receipt is a builder assertion, with publisher
authentication and signed qualification explicitly false.

An application retains normal captured Cargo dependency review and executable
input approval. Its original source WIT must explicitly import
`latent:http/streaming@0.3.0`, `latent:runtime/activation@0.1.0` and
`latent:clock/monotonic@0.1.0`. The maintained build accepts
`--http-runtime /absolute/owned/http-runtime`. Emitted WASI imports confer no
authority, and no version alias is installed.

This selected profile requires each public entry to declare its blocking effect
explicitly, for example `greet: async func(name: string) -> result<string, string>`.
Ordinary synchronous Rust implementations use the pinned normal generator option
`async: false`; this selects a synchronous Core ABI while retaining the async
function type in the embedded component metadata. It adds no executor, future or
transport to the application or either published client. A selected synchronous
public contract is refused with `rust-http-selected-explicit-async-export-required`.
The default non-HTTP authoring contract and generator selection are unchanged.

Installed Rust tools can explicitly capture that same prepared runtime during
nonpublishing bundle assembly:

```sh
python3 -B tools/build_dev_guest_tools.py --language rust \
  --output "$PWD/target/rust-http-tools" --python-prefix /usr/local \
  --rust-http-runtime /absolute/owned/http-runtime
```

This option is assembly-only and has source/control evidence; an installed
bundle build has not yet been qualified. Assembly checks the exact staged Rustc
and wasm-tools bytes, preserves the original producer receipt and source
inventory, and copies only the four component/WIT files and pinned composer.
The complete 113-file consumer recipe and all seven retained runtime files join
the existing authenticated tool inventory. Installed compilation resolves the
application's exact package/version/world using the pinned whole-WIT reader and
selects this adapter only when that world declares all three interfaces above.
Pure templates and partial declarations retain the ordinary builder path and
its concrete import refusals. Selection grants no provider authority and uses
no application or library identity.

The compiler composes a generated forwarding root around the actual application
component. The root's application imports and public exports must exactly match
the explicitly selected async contract, including function kinds and nominal
value ownership. Its generated Rust bindings also use `async: false`. Each call
retains its actual value or error until the private drain returns. The first bridge supports finite unnamed value APIs; named aggregate,
resource and unsupported borrowed-aggregate exports receive concrete build
diagnostics. `publicGraphUnchanged` refers to that explicitly declared selected
contract; it never describes a conversion of an older synchronous component.
The compiler uses the captured
offline compiler namespace and wires exact nominal interfaces through the
pinned composer. Only the internal blocking operations and private drain are
projected; every original application core byte must survive. Final WASI/private
imports or undeclared authority fail the build before packaging.

The pending qualification must exercise actual signed two-client/developer-crate
calls, real provider errors and denials, partial I/O, cancellation, uncertain
POST without replay, lifecycle retirement, physical owners and fresh tenant reuse.
The historical [compiler-only observation](rust-wasi-http-inputs.md) remains
separately attributable and retains its original compatibility failure.

The original synchronous `ceff0697...` component and private diagnostic remain
historical failures. [Run 39571821467](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39571821467)
retained the closed `cannot-block-sync-task` trap from its first ordinary Waki
call; the diagnostic is not qualification. The Component Model's
[concurrency contract](https://github.com/WebAssembly/component-model/blob/main/design/mvp/Concurrency.md)
distinguishes a function's async effect from its Core ABI. Generator-only controls
verify the explicit contract and unchanged ordinary source bodies; fresh signed
execution is still required for the corrected profile.
