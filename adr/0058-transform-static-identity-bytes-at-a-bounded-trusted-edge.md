# ADR-0058: Transform static identity bytes at a bounded trusted edge

Status: Accepted

## Context

The native static service authenticates immutable identity representations. A
frontend comparison with a gzip-enabled server must account for different
transfer bytes. Integration feedback permits either signed native variants or a
qualified bounded edge. No prior performance regression has been measured.

## Decision

Extend the local HTTPS edge from ADR-0057 with explicit `compression: "gzip"`.
The default remains streamed identity. The native node authenticates original
package bytes and current publication eligibility on every request; it admits no
new encoding or unsigned package variant. The trusted edge transforms those
verified bytes using its pinned Node/zlib implementation and authenticates the
result to the browser with TLS. Publisher signatures do not cover these derived
gzip bytes. Operators must trust the edge as part of their serving infrastructure.

Parse at most 512 bytes and 16 encoding preferences. Honor explicit quality
values, wildcard precedence and identity exclusions; malformed/duplicate values
return 400 and no acceptable supported encoding returns 406 after native
authorization. Missing or empty preferences select identity. Successful identity
and gzip responses vary on Accept-Encoding. Hash the actual encoded bytes with
a profile and media-type domain for their strong ETag; never reuse the identity
strong ETag. Apply If-Match before If-None-Match, with strong and weak comparison
respectively, after native eligibility. Preconditions are bounded to 2 KiB,
16 quoted tags and 128 bytes per opaque tag. Range and date preconditions are
outside this closed profile and return 400.

HEAD first authorizes its real native HEAD route. Gzip additionally reads GET
and requires its identity validator, media, length, CSP, cache policy and Vary
to match HEAD before transforming it. Divergent routes fail with 502; neither
method can authorize the other. GET/HEAD/304 share the selected representation
validator and encoding; 304 has no body or Content-Length. Errors never become
cached gzip successes. The native node remains authoritative for all browser
headers, Origin, Fetch Metadata, tenant selection and publication revocation.

Use at most four compression exchanges, with one accepted zlib job each on a
fixed four-thread pool. Read at most 8 MiB and produce at most 8 MiB + 64 KiB.
There is no content cache, retry, per-site worker or decompression. Budget up to
three body-sized buffers per exchange for original bytes, zlib chunks and its
concatenated result; run the compression container with 384 MiB, 128 MiB V8
old-space and 32 task slots. Header, connection and five-second exchange limits
remain as in ADR-0057. Cancellation destroys transport immediately but retains
the exchange until any already accepted bounded zlib callback and sockets have
settled. Shutdown reports zero owners only after this cleanup. The native node
has its own independent resource and physical-work limits.

## Evidence and consequences

The real native-container/TLS drill packages and signs two deterministic 2.5 MiB
JavaScript transfer fixtures using the released CLI. It verifies exact decoded
source identity, negotiation, GET/HEAD/304 and both preconditions, independent
HEAD routing, missing paths, revoked publication, actual uncached source damage,
encoded checksum damage, distinct publications, restart and zero native dormant
owners. Three serial samples per representation record body transfer sizes and
request times. These deliberately repetitive fixtures are not a framework
benchmark or evidence of a previous regression.

Compression costs buffering and CPU on every request, including conditional
requests and gzip HEAD; HEAD requires two native requests. There is no retained
gzip variant to corrupt or reclaim. Native package schemas/storage limits do
not change. Persistent admitted variants, Brotli, ranges and general CDN behavior
would need separate reviewed contracts. No cloud resources or simulated Azure
qualification are involved.
