# Standard HTTP library conformance

`latent.standard-http.conformance.v1` identifies the common controlled-peer
vectors and observation predicates in [tools/standard_http](../../tools/standard_http/).
They exercise HTTP operations independently of library names. The initial
implementation qualifies the bounded peer protocol only. Language/component
receipts below have their own source and execution scope; the peer alone proves
no ordinary default client or host memory accounting.

## Current host contract

The authoritative streaming interface is
[`latent:http/streaming@0.3.0`](../../wit/platform/http-v3/package.wit), implemented
by the existing `bounded-streaming-http-identity-v1` provider. The explicit
[normal-node installation](../reference/standalone-providers.md#streaming-http-installation)
and Rust embedding API install that same provider. The buffered HTTP 0.2 profile
remains separately identified in [outbound HTTP](../runtime/outbound-http.md).

The common request mapping preserves GET, HEAD, POST, PUT, PATCH, DELETE and
OPTIONS; the URL, header list, status and body bytes; and absent versus present
body length and media type. Header names/values in the typed WIT are strings.
Body bytes can contain arbitrary binary data. A native library's different
header encoding or normalization must be recorded and compared with its
reference API; the WIT does not promise arbitrary eight-bit header strings.
HTTP 4xx/5xx are responses. Transport, authorization and limit failures remain
distinct from domain parsing failure on an otherwise valid response.

HTTP 0.3 has eight async operations: `open`, `write`, `finish`, `read`,
`chunk-bytes`, `trailers`, `abort-upload` and `abort-body`. `finish` consumes the
upload. A body remains owned through EOF and trailer lowering. A read chunk is
materialized once and remains owned through the returned bytes' lowering.
`read` returning `none` means verified EOF; an empty chunk does not mean that a
pending producer completed. Keep the original upload/body owner while a
borrowed operation is pending. Early close, cancellation, trap and root drain
must destroy the actual native owners before refund or cell reuse is proven.

The closed WIT errors are `invalid-url`, `invalid-request`, `permission-denied`,
`request-too-large`, `response-too-large`, `deadline-exceeded`, `cancelled`,
`budget-exhausted`, `dns-failed`, `tls-failed`, `connection-failed`, `unavailable`,
`uncertain`, `invalid-state`, `unexpected-eof` and `unsupported-encoding`.
Each language profile must preserve their meaningful distinctions through its
ordinary public API. In particular, possible dispatch followed by a lost reply
cannot become a claim that a POST did not execute. An idempotency key does not
authorize another attempt. This provider adds no retry or redirect.

Provider installation confers no guest authority. An initial request needs the
actual current provider profile/digest/epoch, binding, publication, policy and
deployment grants, including exact HTTP method/path/header resources. Existing
profile semantics govern accepted continuation authority; those continuations
retain the original destination, ceilings and monotonic deadline. An operation
timeout only narrows that deadline. Reserved credentials/framing, DNS/SSRF,
TLS, redirect destinations and credential stripping remain enforced by the
selected host profile. Streaming HTTP accepts identity-encoded response bodies
only. HEAD responses and statuses 204 and 304 have no body: their
`Content-Encoding` representation metadata is preserved without decoding or
charging a representation `Content-Length` as transferred body bytes. This
follows [RFC 9110 sections 6.4.1 and 9.3.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-6.4.1).
An encoded GET entity response still returns `unsupported-encoding`, even when
its declared length is zero. A buffered profile's decompression support is not
inherited by this interface.

Opaque TCP/TLS bytes require the separately reviewed stream contract and exact
endpoint/port/transport grants. Neither a missing typed HTTP mapping nor a
denied request can select a broader socket/WASI/syscall fallback. A known API
boundary may map directly to typed HTTP without waiting for raw-stream approval.

## Controlled peer vectors

Each fresh peer owns two explicit IPv4 loopback origins. The primary requires
a private provider credential; the secondary rejects authorization, cookie and
proxy-authorization forwarding. The credential is provided explicitly, never
read from the environment and never copied into observations. Installation
inputs returned by `provider_destinations()` contain no policy/grant or
credential. The runner installs the primary credential through the maintained
protected store and separately grants only the intended HTTP resources.

| Vector | Observable operation |
| --- | --- |
| `domain-json` | UTF-8 domain JSON with non-ASCII strings and an empty value |
| `http-404`, `http-500` | Actual error-status responses containing domain JSON |
| `method-bytes` | Seven methods, binary/UTF-8 bodies, absent/present zero length and custom headers |
| `pending-headers` | Complete request held before any response header |
| `partial-body` | Response headers and five bytes, then the remaining body behind a gate |
| `pending-upload` | Request headers observed while body consumption is held |
| `truncated-body` | Declared length 32 followed by only five bytes and real close |
| `malformed-framing` | Conflicting content length and transfer encoding |
| `malformed-json` | A valid HTTP response whose domain JSON is incomplete |
| `oversized-body` | A real 64 KiB response for a separately configured narrower limit |
| `gzip-json` | Actual gzip GET bytes are unsupported by identity-only streaming; HEAD preserves the encoding/length metadata with no payload |
| `redirect`, `redirect-target` | Two distinct origins and explicit credential-presence observations |
| `redirect-denied`, `denied-target` | A redirect toward an independently ungranted destination |
| `commit-pending` | One POST mutation committed before withheld response headers |
| `commit-close` | One POST mutation committed followed by close without a response |

`Gate(generation, request, phase)` refers to one actual pending peer connection.
It releases once. Foreign, stale, repeated and stopped-generation gates fail
without changing another connection. A gate is a supervisor readiness witness,
not a guest wake, a cancellation acknowledgement or permission to rerun a call.
The selector can be shared with the runner's own process/connection supervision;
the peer supplies no worker thread or executor. A separate ready response can
progress while an upload, header or body gate is held.

The peer admits at most four live connections and 32 total contacts, retains at
most 512 events, receives at most 2 MiB total, and lives at most 300 seconds
(60 by default). Each request is bounded by 30 seconds, 256 KiB of body, 8 KiB
of headers, 32 fields, an 8 KiB unread window and 1024 chunk frames. Responses
are bounded by 64 KiB. These are fixture limits, not increased host allowances.
Use fresh bounded peers when the complete campaign exceeds 32 contacts.

Snapshots contain generation, origins, limits, finite counters, connection
states, body lengths/digests and ordered events. They contain no credential,
payload byte, OS exception or guest success marker. Predicates reject changed
origins, generations, limits/history, malformed owners and counter regressions.
`require_zero_contact` additionally requires both listeners to remain live.
Even an empty TCP connection defeats it. An exhausted/stopped peer cannot prove
authorization denial. `require_one_committed_request` detects a second observed
attempt or mutation rather than hiding retries behind deduplication.

Remote FIN, peer close and response write completion describe the peer. Pair
them with original broker/I/O/native/guest ledger reservations, actual physical
owner destruction and authenticated node cleanup. None alone proves a refund,
root result eligibility, cross-tenant freshness or external rollback.

## Language port plan and qualification

The host operation/error/ownership contract above is reusable. An API/runtime
profile additionally identifies its supported constructors, options, sync/async
paths, body APIs and runtime initialization beneath direct/transitive code.
Unsupported members need precise #679 diagnostics. An optional injected
transport remains a separate public extension and cannot qualify a default path.

| Language | Ordinary API and default backend selection | Initialization / async ownership | Current delivery boundary |
| --- | --- | --- | --- |
| Java #688 | `URL.openConnection()` / `HttpURLConnection` through the compiler-owned connection factory; unchanged callers keep that factory | Maintained TeaVM connection implementation; synchronous acquisition/body ownership, with #741 owning wider logical-thread/timer semantics | Actual standard and published `http-request` signed subsets, plus private captured wrappers; complete two-client/options/async/TLS matrix remains with #688 |
| Rust #689 | Planned `reqwest::Client::new()`, `Client::builder().build()` and `RequestBuilder::send().await` through reqwest's ordinary native backend | Planned Tokio runtime, timer and reactor integration beneath unchanged dependency code; #743 owns runtime support | Named reference plan below; no maintained default reqwest backend or qualified LSF runtime profile is claimed |
| C #690 | Planned libcurl easy API: `curl_global_init`, `curl_easy_init`, `curl_easy_setopt`, `curl_easy_perform`, `curl_easy_getinfo`, `curl_easy_cleanup` | Planned libc/platform port plus ordinary libcurl multi readiness/callback path for asynchronous use; #744 owns runtime support | Named reference plan below; no maintained libcurl port or qualified LSF runtime profile is claimed |
| TypeScript #691 | `globalThis.fetch`, `Request`, `Response`, `Headers`, `AbortSignal`; maintained compiler-owned global implementation, without injected transport | App-realm promises, body/abort continuation and #745 microtask/runtime owner | Actual parsed UTF-8/HTTP-error/fresh signed subset; complete browser-compatible options/body/async matrix remains with #691 |
| Go #692 | `http.Client`, `http.DefaultClient`, `http.DefaultTransport` and advertised `Transport` members through the maintained standard-library backend | Maintained Go activation/net-poll/context ownership; #742 owns the wider runtime | Actual normal, standard and adversarial signed subsets including redirect/credential and root-retirement controls; complete standard-client contract remains with #692 |
| .NET #693 | Ordinary `HttpClient` / BCL handler through the selected `dotnet-http-runtime` composition, without application handler replacement | Activation-owned WASI HTTP/poll/stream adapter; #746 owns the wider managed runtime | Actual original, synchronous `Send` and async/pre-cancel signed subsets; complete handler/options/managed-runtime contract remains with #693 |

### Named Rust and C reference plan

These are implementation targets for #689 and #690, not new package eligibility
rules or shipped backend profiles. Capture the selected library version, features,
TLS/resolver backend, target, runtime/automatic patch and final WIT identity before
qualifying a port. The shared contract does not require every language port to
finish before a direct API mapping can ship.

The Rust reference is [reqwest 0.13.5's native async `Client`](https://docs.rs/reqwest/0.13.5/reqwest/struct.Client.html)
and its [builder options](https://docs.rs/reqwest/0.13.5/reqwest/struct.ClientBuilder.html).
Its [versioned native backend manifest](https://github.com/seanmonstar/reqwest/blob/v0.13.5/Cargo.toml)
selects hyper/hyper-util with Tokio networking/timers; `default-tls` selects
rustls, with its explicit crypto-provider and platform-verifier dependencies.
Those default backend dependencies must be ported/captured or refused precisely,
not silently replaced by a different application client or permissive verifier.
Its ordinary factory, initialization failures, response/status/body/error values
and connection reuse must remain observable through unchanged dependency calls.
The native API is target-gated upstream; naming it does not make it available on
the maintained component target. #689 must supply and qualify the underlying
Tokio readiness/timer/backend integration rather than requiring a caller-provided
LSF client, executor or transport. Ordinary `#[tokio::main]` and
`tokio::runtime::Builder` initialization must either select a supported scheduler
with its actual worker/timer limits or refuse precisely; a multithread selection
cannot silently become a single-thread executor. A blocking facade needs
separately supported logical-thread parking; synchronous waiting on an async
export is insufficient.

The C reference is the [libcurl easy interface](https://curl.se/libcurl/c/curl_easy_perform.html),
with ordinary [global/easy initialization](https://curl.se/libcurl/c/curl_easy_init.html),
write/header callbacks, result codes and cleanup. Asynchronous use selects the
[libcurl multi interface](https://curl.se/libcurl/c/libcurl-multi.html):
`curl_multi_init`, `curl_multi_add_handle`, `curl_multi_perform`,
`curl_multi_poll`, `curl_multi_info_read`, `curl_multi_remove_handle` and
`curl_multi_cleanup`. #690 must pin a concrete libcurl release/build and preserve
its C ABI, callback ownership and readiness behavior; no libcurl version is yet
a qualified LSF HTTP profile. A port may map known HTTP operations to typed HTTP.
A socket-level backend instead needs independently approved opaque stream/TLS
composition and exact endpoint grants; it cannot derive typed HTTP authority by
inspecting bytes or fall back to sockets after a typed denial.

For both plans, record reference defaults and explicit option changes for
redirects, retries, proxies, authentication, cookies, pooling, decompression,
TLS and connect/read/total timeouts. Preserve them where supported. Reject
unsupported selections precisely before effects instead of silently disabling
options, adding attempts or substituting success. Every additional library call
remains independently authorized and charged. Per-call timeouts narrow the
original root deadline; neither initialization nor a reconnect resets it.

### Existing closed WASI HTTP composition

The maintained .NET example is a concrete composition profile, not a claim that
all WASI HTTP versions or all language runtimes work. Its internal interfaces are
[`wasi:http/types` and `wasi:http/outgoing-handler` at `0.2.0`](../../sdk/dotnet-guest/runtime/wit/deps/http.wit),
with [`wasi:io` poll/streams at `0.2.6`](../../sdk/dotnet-guest/runtime/wit/deps/io.wit).
The [runtime selector](../../tools/dotnet_guest/runtime.py) requires both actual
emitted HTTP imports and exact declared `latent:runtime/activation@0.1.0` and
`latent:http/streaming@0.3.0` authority to select `dotnet-http-runtime` (or its
separately selected logging variant). Declared authority alone selects no HTTP
adapter. Unsupported versions, duplicate imports, ambient WASI declarations and
undeclared emitted imports refuse.

The [compiler](../../tools/dotnet_guest/compiler.py) composes the emitted graph
through the selected adapter using the pinned component toolchain. The
[composer](../../tools/dotnet_guest/composer.py) binds exact named edges and checks
the resulting graph and binary again. Canonical ABI/resource compatibility is
checked by real composition, not import renaming or semver substitution. Final
imports must stay within the declared LSF surface; no filesystem, socket or
process authority is supplied by the internal WASI interface names.

Historical signed evidence includes [#1085's original plus synchronous `Send` cases](https://github.com/KirilsTurkins/latent-service-fabric/issues/693#issuecomment-6258891568)
and [#1091's original plus async/pre-cancel cases](https://github.com/KirilsTurkins/latent-service-fabric/issues/693#issuecomment-6261245915).
Each preserves its own component, compiler, adapter, host and source identities;
these receipts are not rebound to current source. They establish a useful
closed-WASI outgoing HTTP slice, including real peer calls and retirement, while
#693/#746 retain their broader unsupported and unqualified surfaces.

Every row must execute at least two unchanged independently maintained clients
through the same selected backend and ordinary constructors, plus a compatible
outside-checkout dependency absent from SDK catalogues. Vary package identity
and remove catalogue data without changing LSF/backend code. Capture exact
direct/transitive source, compiler, target/sysroot, runtime/automatic patch,
backend, WIT, engine and component identities through #678. Actual signed and
admitted components must drive the real provider; native reference/parser/peer
checks supplement that evidence.

The common campaign includes parsed success and HTTP errors; absent provider or
grant and denied targets with zero contact; reserved headers and redirect
credentials; actual DNS/TLS/SSRF/currentness controls; oversized/malformed/partial
bodies, backpressure, EOF/trailers and early close; timeout/cancel before and
after dispatch; uncertain POST with one commit and no hidden replay; root closing
with accepted work; task/timer/memory limits and sibling readiness; late wakes,
actual owner retirement and fresh cross-tenant reuse. Record ordinary library
retry/redirect/proxy/auth/cookie/pool behavior rather than silently changing
defaults. Library-issued additional calls require their own authorization and
charges. The loopback peer implements only the vectors in the table; the deeper
DNS/TLS and physical ownership campaigns remain required separately.

Useful closed WASI composition must preserve shared resource identities and
actual semantics. Renaming imports, trapping supported operations, returning
fake successful resources or joining a Promise/Task with a synchronous export
cannot satisfy the supported profile. Existing synchronous SDK and pure library
profiles remain separately documented while runtime ports qualify.

Run the bounded peer controls with:

```sh
python -m unittest tools.tests.test_standard_http
```

The initial Windows run passes 30 peer/parser/observation controls. Normal-node
streaming installation also passes three closed schema controls and four native
Rust configuration/startup controls at source `4c47482b`. The pinned Rust 1.97.1
Linux run builds every workspace crate from this source, retaining only external
dependency caches; no older workspace executable qualifies it. The test binary
is 170,246,304 bytes with SHA-256
`a13c687e2f6c9b9e4b0404bcf9a926c60d68f2b35de56b5e03240cc3fbd54ed0`.
The ordinary production-feature lifecycle control starts/stops 32 nodes and
verifies credential retirement, clean I/O ownership and no destination contact.
Both earlier setup failures are retained separately from the passing attempt.
No standard language client, complete #680 acceptance, or production raw-stream
enablement is claimed by these source and fixture checks.

### Bodyless representation metadata

The source regression cases cover HEAD 200, GET 204 and GET 304 with gzip
representation metadata, empty EOF/trailers, and owner retirement. HEAD/304
advertise a 4096-byte representation under an unchanged 1024-byte streaming
output limit; no response body is transferred or decompressed. An actual
resource-component control uses the same three responses through the frozen
streaming ABI and checks the original activation budget, empty I/O ledger,
clean pools and reusable execution. Encoded GET 200/302 entity responses remain
unsupported. The controlled peer also verifies real HEAD gzip metadata and an
empty wire payload.

The [#1074 bodyless slice records the actual host/component result](https://github.com/KirilsTurkins/latent-service-fabric/issues/680#issuecomment-6257071756).
That source-bound receipt supplements the peer controls; it does not qualify
all language APIs or every vector. Provider identity, WIT, limits and authority
rules are unchanged by the metadata correction.
