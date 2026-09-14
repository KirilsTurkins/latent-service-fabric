# Bounded streaming HTTP

`latent-http::StreamingHttpProvider` implements the canonical async
`latent:http/streaming@0.3.0` interface. Its installed profile is
`bounded-streaming-http-identity-v1`. It reuses the [buffered HTTP](outbound-http.md)
origin, path, method, header, credential, DNS, TLS and shared-pool controls.
GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS are supported. A 4xx/5xx status is
a response. No ambient network authority, WebSocket, CONNECT, protocol upgrade,
automatic replay or automatic redirect is provided.

This is an explicit trusted embedding API. Standalone provider composition remains
[#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226).

```rust,ignore
let provider = StreamingHttpProvider::install(pools.clone(), "streaming", 1, 0,
    http_configuration, HttpStreamLimits::default(), &credentials)?;
let reference = provider.reference(); // bind this exact profile/digest/epoch
runtime.install_streaming_http(std::sync::Arc::new(provider))?;
```

The streaming configuration requires `maximumRedirects = 0` and empty destination
redirect lists. Redirect statuses and bounded `location` headers are returned to
the guest. A guest choosing another request needs another independent grant and
outbound-request charge. Buffered `client@0.2.0` retains its existing semantics.

## Resource contract

[The frozen WIT](../../wit/platform/http-v3/package.wit) defines three resources.
Every resource belongs to one fresh Store and one original accepted operation.
A resource representation is lookup data, never an authorization token for
another Store, tenant, cell, provider or request.

| Operation | Behavior |
| --- | --- |
| `open(request)` | Admit exact metadata and return an owned upload. `body-length = some(n)` commits to exactly n bytes; `none` selects bounded HTTP/1.1 chunked framing. |
| `write(borrow<upload>, bytes)` | Submit one nonempty bounded chunk. Wait for transport consumption or response/failure; success does not promise remote application processing. |
| `finish(upload)` | Consume the upload, verify its declared length, finish request framing and return validated status/headers plus an owned response body. |
| `read(borrow<body>, maximum-bytes)` | Return at most that many bytes as an owned chunk. `none` means verified EOF, including valid framing and length. |
| `chunk-bytes(borrow<chunk>)` | Materialize bytes once. A second call returns `invalid-state`; drop the chunk after the first call returns. |
| `trailers(borrow<body>)` | Materialize validated trailers once, after verified EOF. Premature or repeated calls return `invalid-state`. |
| `abort-upload(upload)` / `abort-body(body)` | Consume the owner and close its real I/O. Bytes already sent cannot be undone. |
| Resource Drop | Synchronous, bounded destruction. No network wait, detached drain or cleanup worker. Separately held chunks retain their own data and charges. |

An overlapping operation on the same busy upload/body is rejected. Taking a
resource across an await moves its actual owner into that future. Cancellation
cannot restore a dropped or stale entry. Wasmtime checks resource types and
borrow lifetimes. Preparation separately verifies exact own/borrow positions
because the typed resource linker accepts either ownership form. The host
additionally checks type, Store-local membership and
nonreused process-wide representation. The 64-entry table is allocated lazily
with a Store-lifetime metadata reservation. Empty slots retain no provider call
or running permit; its backing storage remains charged until Store destruction.

The Rust embedding port exposes affine `HttpUpload` and `HttpBody` trait objects.
These must be dropped after completion/abort. Dropping only a borrowed write/read
future does not prove that a separately retained upload/body has been destroyed.
The guest adapter owns the complete object while suspended, so guest cancellation
and Store destruction destroy that owner.

## Limits and backpressure

| Limit | Default | Hard profile ceiling |
| --- | --- | --- |
| Total uploaded bytes per operation | 16 MiB | 63 MiB |
| Total downloaded bytes per operation | 16 MiB | 63 MiB |
| Chunk capacity | 16 KiB | 64 KiB |
| Outstanding upload/output chunks per operation | 4 | 32 |
| HTTP headers and trailers together | 8 KiB, 32 fields | 32 KiB, 64 fields |
| Store upload/body/chunk entries | 64, allocated on first open | 64 |

The node broker has separate cumulative stream input/output ceilings (16 MiB
default each). Policy input/output ceilings cover inline metadata **plus** the
full declared transfer allowance at both initial and final dispatch checks. An
unknown upload length uses the provider's configured input allowance. This is
an authorization ceiling, not a whole-body allocation.

Only an explicitly accepted `CapabilityStreamBudget` can issue an `IoTransfer`,
and each accepted operation can issue it once. Accepted byte totals never refund
when chunks are dropped. Live storage has separate refundable reservations:
actual input vector capacity, output chunk storage, one output lowering copy,
metadata, stream count, and retained result capacity. Ordinary buffered calls
cannot use a transfer to reset their existing per-call result limit.

The upload queue has one pending frame. Its empty state contains no activation
reference. Hyper's fixed 32 KiB read buffer may retain one response frame in
addition to guest chunks; protocol and scratch reservations cover that storage.
No body-sized response vector, request queue or detached HTTP driver exists.
Only the active operation future drives the connection. A full guest chunk
window returns `budget-exhausted` before another transport read; drop a held
chunk before retrying. TCP backpressure suspends an upload within the same
original deadline and finite input window.

Provider, broker, I/O, policy, pool and canonical-lifting limits intersect.
Increasing a provider setting alone does not increase the others. These are
logical ownership bounds, not total RSS measurements or an OS scheduling bound.
Completed, healthy connections are reusable only after upload/response EOF,
no outstanding chunk, no retained request bytes, and sender readiness. The idle
entry must retain no activation or transfer reference. Otherwise it is closed.
Keep the body until headers/trailers finish lowering; then drop it to release the
original operation. Preparing dormant capsules creates no resource table or I/O.

## Framing, cancellation and outcome

The provider sends `Accept-Encoding: identity`. Nonidentity content encoding is
rejected as `unsupported-encoding` before any body is exposed. Encoded and decoded
byte counts therefore have a 1:1 limit in this profile. Buffered HTTP retains
bounded gzip/deflate support. Streamed decompression would need a subsequent
versioned transport profile with independently bounded decoder state.

Conflicting/invalid length and transfer-encoding, oversized headers/trailers,
invalid trailer fields and oversized frames fail closed. A short declared upload
returns `unexpected-eof`; writing past its declared length is rejected before
queueing. Premature response EOF or truncated chunk framing is an error, never
`none`. Post-header failure remains terminal and cannot be read as later EOF.
Headers alone do not promise a complete response body. HEAD and 204/304 have no
body, independently of a representation length advertised by the peer.

The original monotonic deadline covers queue, DNS, connect, TLS, upload, headers,
body and trailers. A requested timeout may only narrow it. Required audit and
current grants are checked at the final `open` dispatch boundary, before network
work. A finite accepted operation may finish after policy revocation; its
continuations cannot change destination, tenant, grants, byte allowance or
deadline. A new `open` must pass current authorization again.

Before a valid response header, failure after a possible HTTP write is
`uncertain`. An idempotency key gives no retry authority. A validated header
records `http-response-received`, even if the body later fails. Audit commits
metadata, declared framing/allowance and an opaque request digest; it does not
claim to hash future payload bytes. Drop does not wait for terminal audit
persistence, and incomplete audit durability remains explicit. None of these
receipts implies transactional coupling, rollback or an application outbox.

## ABI and validation

[ADR-0032](../../adr/0032-use-bounded-owned-resources-for-streaming-http.md) selects
`lsf-host-abi-phase3-v3`. V1/V2 WIT and profile identities remain unchanged.
V3 adds only the exact upload/body/chunk resource identities of this host import.
Application exports still use the supported value profile. Other resource,
implicit future/stream, changed own/borrow, wrong version and wrong async shapes
are rejected. The V3 digest enters prepared/native identity; rebuild the node and
AOT compiler together and regenerate incompatible cached artifacts.

The baseline remains Wasmtime 47.0.4. On 2026-09-14 the upstream patched ranges for
[RUSTSEC-2026-0268](https://rustsec.org/advisories/RUSTSEC-2026-0268.html) and
[RUSTSEC-2026-0269](https://rustsec.org/advisories/RUSTSEC-2026-0269.html) include
47.0.4. The actual installed extension uses explicit resources and bounded byte
lists; it installs no WASIp3 built-in stream or WASI filesystem imports. This
is a reachability review of this profile, not a blanket exemption for future
interfaces. Canonical hostcall fuel and the signature allocation proof remain
active for every value leaf. CI advisory scanning now also triggers on changes
to platform WIT, installed host imports and binding generation.

The [maintained guest](../../examples/streaming-http/README.md) executes real
uploads, chunk reads, one-time materialization, EOF/trailers, aborts and traps.
Tiny real TCP fixtures check first-chunk delivery before completion, finite
producer/consumer windows, truncation, encoding rejection, deadline/cancellation
and actual connection reuse. A 256-deployment dormant cohort leaves provider,
I/O and broker ownership counters unchanged and creates no activation Store.
No 100k execution or throughput claim is made.
