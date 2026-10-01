# NativeAOT standard HTTP implementation and qualification

This implementation slice connects the pinned .NET 10 WASI HTTP resource
identities to the existing typed LSF streaming HTTP capability. It is development
work for [#693](https://github.com/KirilsTurkins/latent-service-fabric/issues/693)
and the shared runtime work in
[#680](https://github.com/KirilsTurkins/latent-service-fabric/issues/680).
Actual component compilation, ordinary default-client execution and complete
acceptance qualification remain pending. The source does not establish a
supported `HttpClient` or default ThreadPool release profile.

## Declared authority and exact composition

The compiler selects support from the parsed authoritative application WIT and
the actual emitted NativeAOT component graph. Retained WASI HTTP imports alone
grant no network authority. All final LSF imports must belong to the declared
application imports; ambient WASI imports must be eliminated by exact component
composition and rejected by ordinary host admission if any survive.

| Source declaration | Adapter | HTTP behavior |
| --- | --- | --- |
| `latent:clock/monotonic@0.1.0` | `closed` | Exact retained HTTP interfaces return `http-request-denied`; closed streams return their actual `closed` state; filesystem operations return `not-permitted` |
| Clock plus `latent:runtime/activation@0.1.0` | `runtime` | The same HTTP denial, plus activation-owned canonical timer readiness |
| Clock plus activation plus `latent:http/streaming@0.3.0` | `http` | HTTP operations use independently admitted typed HTTP calls and owned upload, body and chunk resources |

The full HTTP profile requires all three exact imports. A grant for
`latent:network/streams@0.1.0` cannot enable the default HTTP backend. Unknown WASI
interfaces, changed interface versions and undeclared emitted LSF imports fail
selection. Exact function and resource shapes still require actual composition
and the frozen host-ABI compatibility checks.

The installer builds each adapter from pinned Rust dependencies. Runtime source
capture includes the complete `sdk/dotnet-guest/runtime` tree, the smoke manifest,
all three example entrypoints and the workspace manifest and lockfile. Independent
project capture includes those same sources. Installed bytes and compiler inputs
are checked again after compilation. `runtime-profile.json` binds the selected
profile, declared/emitted imports, raw component and actual adapter identities;
it is diagnostic evidence, not an authority grant or execution receipt.

## Ownership and readiness

The guest bridge retains original typed import futures until their actual
completion or destruction. A bounded activation-local canonical waitable set
uses the pinned wit-bindgen 0.62 task ABI. Polling one completed resource keeps
other pending calls owned; disposal cancels the exact original subtask. It never
retries an accepted request or creates a replacement activation budget.

Only successful completion of `wait-for` makes a timer ready. Cancellation,
revocation and failed waits cannot become elapsed time. Nonblocking response and
body operations can remain genuinely incomplete. Only verified typed HTTP EOF
becomes the closed input-stream state that the BCL reads as EOF. Pending,
truncated and failed reads keep their error behavior. The same WASI IO resource
identities are shared by the BCL, HTTP bodies and closed compiler support.

Finite guest limits are 64 simultaneously live resource/metadata owners, 32
tracked operations, 64 canonical waitables, 32 headers / 8 KiB header storage,
16 KiB body chunks and 1 MiB request bytes. These limits supplement the original
Wasm memory ledger and independently narrower host/provider limits. They are
not a physical native-memory measurement. Original host reservations remain
charged through actual physical future/socket destruction.

## HTTP behavior and remaining requirements

The bridge supports the seven methods in the typed HTTP capability. Host,
framing, credential, hop and content-encoding headers remain provider-controlled.
Content type, known body length and idempotency key use their existing typed
request fields. Unsupported request options return configuration errors.
Response bytes and headers retain the streaming provider's identity-encoding
profile; this source does not silently enable automatic decompression, redirects,
proxy, cookie or ambient TLS settings. The pinned WASI BCL also explicitly
rejects its unsupported settings and synchronous send path.

Original host failure categories remain sticky on the exchange. Local body or
protocol faults after a started import keep conservative uncertainty and abort
that exact owner. The WASI error
enum distinguishes denied requests, DNS failure and incomplete response and
carries `latent-http-*` markers in `internal-error` for the remaining typed
categories, including uncertainty. The pinned BCL's `ErrorCodeToString` discards
that payload in the
[pinned handler source](https://github.com/dotnet/runtime/blob/v10.0.0/src/libraries/System.Net.Http/src/System/Net/Http/WasiHttpHandler/WasiHttpHandler.cs).
A source-bound BCL change and actual ordinary
`HttpRequestException` evidence are required before claiming end-to-end
uncertainty preservation. Guest enum markers alone do not meet that criterion.

The selected BCL emits an opaque `future-trailers` resource without observation
methods. The bridge retains its original body through that resource and never
fabricates empty trailers, successful drain or rollback. General trailer APIs,
default ThreadPool/Task.Run/Task.Delay lifecycle, CPU sibling progress, held-open
body controls, original native/frame prepayment and stale-generation shutdown
still require their prescribed unchanged-library, actual-component and node
evidence. They remain open under #693 and the .NET runtime issue #746.

Required body controls include ordinary content finishing before `Handle`, an
incomplete producer with queued bytes, body-length mismatch after a started
import, local write-window violation after possible dispatch, forbidden trailers,
and a committed POST whose response is lost. The first case must preserve the
already finished body; post-start faults must retain uncertainty and never
replay. These controls must use actual default-client components. Source review
fixes alone do not establish their successful execution.

## Evidence available for this slice

The focused authoring suite passes 27 Python cases, including seven added
authority/version/capture controls. The pinned WIT generator parses all adapter
worlds and emits their exact traits. Rust formatting and source checks establish
source validity only. No local heavy NativeAOT, Wasm Rust or node qualification
was run for these new adapter bytes during the shared disk-capacity pause.
CI installation now requests all three actual `wasm32-unknown-unknown` builds;
those results and exact-head component/node evidence must be reviewed before
delivery or issue closure.
