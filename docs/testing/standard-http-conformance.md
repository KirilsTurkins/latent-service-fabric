# Standard HTTP library conformance

`latent.standard-http.conformance.v1` identifies the common controlled-peer
vectors and observation predicates in [tools/standard_http](../../tools/standard_http/).
They exercise HTTP operations independently of library names. The initial
implementation qualifies the bounded peer protocol only. It does not qualify a
language backend, an ordinary default client, host memory accounting, or #680.

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
selected host profile. Streaming HTTP accepts identity encoding only. A
buffered profile's decompression support is not inherited by this interface.

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
| `gzip-json` | Actual gzip bytes; identity-only streaming must reject the encoding |
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

| Language | Required ordinary API boundary | Runtime prerequisite | Current delivery boundary |
| --- | --- | --- | --- |
| Java #688 | Selected standard HTTP constructor; current source candidate uses `HttpURLConnection` | #741 | Source candidate; complete default-library/TLS/redirect/timeout evidence pending |
| Rust #689 | Useful selected standard/ecosystem API plus its ordinary default reactor/executor | #743 | Shared API/runtime selection and default-client implementation pending |
| C #690 | Useful selected source API/ABI over maintained libc/platform boundaries | #744 | Shared API/ABI selection and default-client implementation pending |
| TypeScript #691 | Ordinary `globalThis.fetch`, `Request`, `Response`, `Headers` and `AbortSignal` | #745 | Actual async export/microtask/body/default-global qualification pending |
| Go #692 | `http.Client`, default client/transport and advertised concrete `Transport` members | #742 | Default transport, goroutine/net-poll/context/body qualification pending |
| .NET #693 | Ordinary `HttpClient` using the maintained WASI/BCL handler | #746 | Three-adapter source candidate; actual CLR/default-client/sibling progress pending |

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
streaming installation has three closed schema controls and four registered Rust
configuration/startup controls; native execution at its new source is pending.
No standard language client, complete #680 acceptance, or production raw-stream
enablement is claimed by these source and fixture checks.
