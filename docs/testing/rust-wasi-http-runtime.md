# Selected Rust WASI HTTP runtime

This source implements a selected backend for the six external WASI 0.2.12
interfaces observed from ordinary, unchanged Waki and Golem clients. The
[actual signed programme](evidence/rust-wasi-http-signed-2026-10-21.json) passed
64 attempts: 52 ordinary cases, one queued holder and 11 pre-entry refusals.
It reuses the original authenticated component, backend and native products.
Individual signed memory, Task and Timer saturation remain required evidence;
this finite result does not close #689 or #743.

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

The maintained installed recipe now has a [signed finite qualification](evidence/rust-wasi-http-installed-2026-10-21.json)
from [run 39663071131](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39663071131):
one guest compiled through `recipe/tools/dev_guest_recipe.py`, both unchanged
clients parsed JSON across two independently authorized tenant publications,
and two pre-entry denials, four contacts, physical/provider retirement and a
clean shutdown passed. This qualifies the installed recipe; release publisher
authentication and the full released frontend remain unqualified.

Assembly checks the exact staged Rustc
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

The signed finite programme exercises two unchanged clients and varied captured
developer-crate coordinates, real errors and independent authority denials,
partial I/O, cancellation, uncertain POST without replay, lifecycle retirement,
physical owners and fresh cross-tenant reuse. Each public case retains its own
original values and SHA/byte identity; the aggregate stays within its original
256 KiB bound.
The historical [compiler-only observation](rust-wasi-http-inputs.md) remains
separately attributable and retains its original compatibility failure.

The original synchronous `ceff0697...` component and private diagnostic remain
historical failures. [Run 39571821467](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39571821467)
retained the closed `cannot-block-sync-task` trap from its first ordinary Waki
call; the diagnostic is not qualification. The Component Model's
[concurrency contract](https://github.com/WebAssembly/component-model/blob/main/design/mvp/Concurrency.md)
distinguishes a function's async effect from its Core ABI. Generator-only controls
verify the explicit contract and unchanged ordinary source bodies. The installed
finite installed programme and the signed 64-attempt programme now prove real
execution of that contract. The separate [individual limits programme](rust-wasi-http-limits.md)
now supplies signed memory/Task/Timer differentials and matched fresh calls.

The `8e6ce8d` installed owning attempt compiled one genuine installed-entry
component with all 32 normal compiler/composition commands passing. Its
compile-only observation correctly omitted a packager. Signing failed before
node execution; that attempt did not retain the signer stderr. The installed
controller now follows the existing ordinary public CLI packaging and provenance
join before signing, inside the unchanged original 900-second compiler clock.
The genuine join preserves the original compiler statement and marker verbatim
and adds the actual packager identity. The corrected installed attempt passed all 32 compiler commands and six signed
attempts using the retained native and backend products. No host or backend
was rebuilt. The original 155 qualifier materials, 245 assembly inputs and 116
Rust recipe inputs remain bound to `ed4fdcbb...`. Current development preserves
all 155 qualifier and 116 Rust recipe bytes at the #1314 integration; five
Java/.NET assembly helpers outside the selected Rust compiler recipe differ,
listed in that observation. The later 64-attempt integration retains all 30
executed replay materials. Its original compiler recipe remains attributed to
88b: a separate Go-only profile-list addition changes one current helper, and
the strict runtime reader has its explicit later source identity. The historical installed inventory
and compiler statements have not been rewritten as a current assembly.
The original [failure observation](evidence/rust-wasi-http-installed-packaging-failure-2026-10-21.json)
remains failed.


The 64-attempt result retains the earlier failed pressure and reader runs. Waki
returns the precise resource error; Golem's exact pressure trap has eight charged
outbound starts and eight accepted TCP connections, with seven parsed complete
responses and one exact preparse close. Both pass physical/provider retirement
and fresh opposite-client reuse. The limiting owner and trap instruction remain
unknown. Peak memory below 16 MiB and positive Task/Wait/Timer ownership do not
prove individual memory, Task or Timer exhaustion. The separate nine-attempt
limits programme supplies those three differentials with their own positive,
physical/provider retirement and fresh gates. Its memory public detail remains
empty and its Timer instruction remains unknown; no blanket runtime or
scheduler qualification is inferred.
