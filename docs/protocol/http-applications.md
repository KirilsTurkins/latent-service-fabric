# Bounded HTTP application contract

`latent:web/application@0.1.0` exports `handle(request) -> response` as a canonical
async function. Its `buffered-v1` profile is defined by
[WIT](../../wit/platform/web/package.wit),
[ADR-0035](../../adr/0035-bound-http-application-values-and-delivery-ownership.md)
and the `latent-ingress::http` implementation. Generated host and guest bindings
are available in `latent-component-bindings::{host::web, web_guest}`.

This delivery provides the contract, bounded mapping and ownership primitives.
The shared HTTP listener is tracked by
[#229](https://github.com/KirilsTurkins/latent-service-fabric/issues/229), with
durable routes in [#223](https://github.com/KirilsTurkins/latent-service-fabric/issues/223).
It does not turn an application's WIT export into a listener.

## Records and authority

| Request field | Meaning |
| --- | --- |
| `profile` | Exactly `buffered-v1`. |
| `method` | `get`, `head`, `post`, `put`, `patch`, `delete`, or `options`. Raw HTTP tokens must have their usual uppercase spelling. |
| `scheme` | Actual transport `http` or `https`, supplied by the adapter. |
| `authority`, `path`, `query` | Canonical routing identity; absent and empty queries remain distinct. |
| `headers` | Ordered records of lowercase names and opaque byte-list values. |
| `media-type` | Optional validated Content-Type, removed from the header list. |
| `body-base64` | Canonical padded base64 of the complete raw HTTP body; empty body is `""`. |

The response contains `profile`, `status`, `headers`, `media-type`,
`representation-length` and `body-base64`. Response header names must already be
lowercase. `representation-length` is an optional unsigned length permitted only
for HEAD or status 304; it describes a representation without transferring it.

**Principal, trace and deadline are host context, not request-body fields.**
The world imports `latent:context/context@0.1.0`; its versioned
`invocation-principal`, `trace-context`, and deadline functions remain authoritative.
The native `TrustedContext` supplies the same principal and trace to normal
activation admission. The exchange's `IncomingDeadline` preserves its monotonic
authority and diagnostic Unix projection. Header strings cannot select these
values, grant capabilities, or extend a deadline.

Authorization credentials are processed by the trusted authenticator before
dispatch. The application mapping removes Authorization, Proxy-Authorization,
Forwarded, every X-Forwarded-* field, traceparent, tracestate and baggage. Trusted
trace handling happens separately under node policy. X-LSF-* impersonation is
rejected. Cookies remain application data and are not converted into a principal.
A generic RPC caller can supply application values; the guest must still read
identity through host context. HTTP provenance and HTTP-specific validation are
provided by the actual HTTP adapter, not by the presence of an HTTP-shaped RPC
payload.

## Byte and allocation limits

| Limit | buffered-v1 |
| --- | --- |
| Raw request / response body | 64 KiB / 256 KiB |
| Header fields / aggregate name and value bytes | 64 / 16 KiB |
| One header name / value | 64 / 4,096 bytes |
| Original path and query / authority | 8,192 / 255 bytes |
| Media type | 256 ASCII bytes |
| Native trusted context / claims and baggage | 8 KiB retained capacity / at most 32 entries each |
| Context string | 512 UTF-8 bytes; no controls |
| Invocation value frame / lexical depth / nodes | 2 MiB / 12 / 32,768 |
| Shared mapping reservation per exchange | 4 MiB |

`HttpPool::new(maximum_exchanges, maximum_bytes)` intersects both ceilings and
rejects excess work immediately. It creates no worker, listener or preallocated
body. Capacity is reserved before copying validated HTTP fields or decoding a
guest response. The protocol parser must apply its own finite head/frame limits
before constructing a borrowed `RawHead`; the mapping cannot undo allocations
already made by an upstream parser.

Response decoding checks raw size, UTF-8, lexical depth and node count before
serde scratch or recursive decoding. Closed typed records reject duplicate,
missing and unknown keys. List lengths are checked before decoding excess
elements. Base64 text has a finite encoded limit; padding determines the exact
decoded length, which is checked before allocating the raw body. Whitespace,
URL-safe alphabet substitutions, missing/excess padding and nonzero unused bits
are rejected. This is [RFC 4648 canonical base64](https://www.rfc-editor.org/rfc/rfc4648.html),
not an implicit byte-list codec extension.

The generic runtime uses the existing
[`application/vnd.latent.wit-values.v1+json`](wit-values.md): one positional array,
closed kebab-case records, enum strings, tagged options and decimal-string u64s.
The explicit body string keeps the largest body out of a list of per-byte runtime
values. A compatible tested Wasmtime configuration selects 2 MiB input/output,
32,768 nodes, 512 KiB strings, 4,096 collection items, 2 MiB hostcall fuel and
64 MiB conservative lifted-allocation allowance; decoded input remains limited
to 16 MiB. Existing global defaults are not raised. These are independent
runtime ceilings, not allocations reserved for every request. Operators must
budget runtime transfers, guest memory, socket/TLS buffers and concurrency
separately from the 4 MiB HTTP mapping reservation.

HTTP bodies and header values remain raw bytes. Body decoding never assumes
UTF-8, parses a media type's content, decompresses a representation or expands a
multipart body. The media grammar accepts type/subtype plus up to 16 unique
token or quoted parameters; its initial profile excludes escaped quoted values,
commas, semicolons inside quotes and non-ASCII media metadata.

## HTTP and URL mapping

The adapter completes and validates the entire header section before dispatch.
HTTP/1.1 requires one Host; HTTP/2 may omit Host, but a supplied value must match
the authority. Duplicate Host or Content-Length is rejected even when values
match. Content-Length is a canonical unsigned decimal and must match the complete
body. Without Content-Length, this HTTP/1.1 profile accepts an empty request body.
GET and HEAD request bodies are empty. An incomplete, excessive or failed
collection cannot be retried as a valid request on the same owner.

Connection, Keep-Alive, Proxy-Connection, TE, Transfer-Encoding, Trailer and Upgrade
are rejected. The transport must reject folded headers, conflicting HTTP/2 pseudo
fields, ambiguous framing and connection reuse after a framing failure before
creating `RawHead`. RPC timeouts alone are not an HTTP parser or connection policy.
These restrictions apply the framing boundary described by
[RFC 9112](https://www.rfc-editor.org/rfc/rfc9112.html).

Header names use HTTP token bytes. Values permit opaque obs-text bytes, but reject
C0 controls, DEL, CR/LF, tabs and leading/trailing spaces. An adapter may remove
HTTP framing OWS exactly once before mapping. Repeated fields preserve order;
the mapper does not comma-join them, choose a first/last value, or reinterpret
Cookie pairs. Every Set-Cookie remains a separate response field, consistent with
[RFC 9110 field semantics](https://www.rfc-editor.org/rfc/rfc9110.html).

Only origin-form targets are accepted. Scheme and DNS host case normalize;
strict IPv4 and bracketed IPv6 spellings are supported. Default ports are removed.
Userinfo, scoped IPv6 zones, trailing DNS dots, leading-zero ports and malformed
host labels are rejected. Percent escapes use uppercase hex and unreserved bytes
are decoded once. Path dot segments, repeated slashes, encoded path separators,
encoded path percent signs, controls and fragments are rejected. Query order,
repetitions, `+`, empty values and encoded reserved bytes remain data; a query is
never reinterpreted as a routing path. Raw non-ASCII targets must be URI-encoded.
Routing and security checks consume `CanonicalTarget` directly and never decode
it a second time. This is the explicit application profile of
[RFC 3986 normalization](https://www.rfc-editor.org/rfc/rfc3986.html).

Responses accept status 200 through 599. HEAD and statuses 204, 205 and 304 have
empty bodies. The adapter derives Content-Length from the body for ordinary
responses, emits zero for 205, omits it for 204, and uses the optional
representation length for HEAD/304. Guests cannot supply Host, Content-Length,
Content-Type, Server, Date, Via, Alt-Svc, forwarding/credential or reserved X-LSF-*
response fields. Informational responses, CONNECT, TRACE, upgrades, trailers and
streaming are outside this versioned profile.

## Failure and delivery ownership

| Outcome | HTTP meaning while a writable response is owned |
| --- | --- |
| Valid application response, including 4xx/5xx | Preserve the application's status and bounded content. |
| Invalid guest response, declared WIT error, trap, incompatible/corrupt dependency | Fixed 502; never reflect the guest error or payload. |
| Unauthenticated / permission denied / missing target | Fixed 401 / 403 / 404. |
| Invalid argument / state conflict | Fixed 400 / 409. |
| Admission, queue or resource exhaustion; unavailable route/provider | Fixed 503. |
| Activation deadline exceeded before the exchange's transport deadline | Fixed 504. |
| Internal/unknown platform failure | Fixed 500. |
| Disconnect, expired exchange deadline, cancelled transport | Close/abort delivery; no fabricated successful response. |

Collection errors map to 400, unsupported methods to 405, request-body excess to
413 and aggregate header excess to 431, if bounded writable error capacity exists.
No mapping implicitly retries an invocation, provider operation or partial write.

The affine ownership sequence is `Collector -> Request -> Invocation -> Delivery`.
Raw-body access borrows its owner. There is no raw-Vec extraction or cloned
response. The adapter must keep invocation ownership until the actual activation
and input cleanup retire, propagate the disconnect signal to normal cancellation,
and wait for that cleanup; signalling does not make an active cell free.
Cancellation handles retain the shared reservation until they too are dropped.

`Delivery` exists before any response write. Mark headers only after their local
write completes; advance body progress only by successfully written bytes. A
successful `finish()` requires both headers and the complete body. Its receipt
means completed local writes, not browser receipt, consumer processing or
transactional commit. Failure after a partial write closes the exchange. Data
fields are dropped before the reservation is refunded. Dormant applications
acquire none of these owners.

## Validation

`cargo test -p latent-ingress --locked` covers goldens, repeated cookies/raw bytes,
framing and URL attacks, closed records, size limits, partial writes, deadline and
disconnect ownership, overload and reuse. Wasmtime unit tests derive actual value
types from the authoritative WIT and check both goldens and maximum response
encoding. Contract CI also builds the Rust `web-contract` fixture, executes the
real ABI with the maximum body and near-limit headers, and observes the trusted
host principal changing between fresh activations. The fixture is an ABI test;
it does not add a package-provenance recipe or constitute an HTTP listener test.
