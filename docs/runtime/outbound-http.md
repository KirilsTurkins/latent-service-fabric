# Policy-scoped outbound HTTP

For owned incremental bodies, use the separately versioned [streaming HTTP](streaming-http.md) profile.

`latent-http::HttpProvider` implements the buffered canonical async
`latent:http/client@0.2.0` import for GET, HEAD, POST, PUT, PATCH, DELETE and
OPTIONS. The versioned provider profile is `bounded-http-v1`. It uses the existing
[broker](capability-broker.md), [I/O owner](async-host-io.md),
[shared pools](provider-pools.md) and [required audit](capability-audit.md).
An HTTP status, including 4xx/5xx, is a response rather than a transport error.

This is a trusted embedding API. Install the provider in an
`ActivationCapabilityRuntime` before preparing its capsules. Compile exact
[provider bindings](capability-bindings.md), supply the original Phase 3 budget
ledger, and grant the actual destination, method and path. An import declaration,
inspection result or provider reference alone grants no network access. Ordinary
standalone/CLI provider configuration is tracked separately in
[#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226).

```rust,ignore
let provider = HttpProvider::install(pools.clone(), "outbound", 1, 0,
    configuration, &credentials)?;
// Use this exact profile/digest/epoch in the compiled provider binding.
let reference = provider.reference();
runtime.install_http(std::sync::Arc::new(provider))?;
```

The provider owns finite configuration, root certificates and DNS cache entries;
shared pool entries own sockets. Dormant services create none of these owners.
Fresh activations never inherit guest state, authority or credentials from a
previous occupant of a reusable execution cell.

## Destinations and credentials

`HttpProviderConfig` format version 1 contains at most eight distinct normalized
origins. Each selects HTTP or HTTPS, an exact lowercase hostname/IP and port,
explicit permitted IP networks, optional exact special-address exceptions, and
one resolution mode. A network alone does not permit loopback, private,
link-local, metadata, multicast, transition or documentation addresses. IPv4-mapped
IPv6 addresses use their IPv4 identity for address checks. Local fixtures opt in
to `127.0.0.1` explicitly.

Static resolution supplies up to eight approved IPs. DNS resolution supplies one
literal recursive-resolver socket and a maximum TTL of 0..300 seconds. There is
no system resolver, search suffix, environment DNS override or resolver task.
A/AAAA packets are limited to 4 KiB, with bounded records, aliases and an eight-IP
answer set. Each origin has one fixed cache slot; TTL zero disables reuse.
Truncated UDP replies can use TCP only to the same configured resolver. Every
returned address is checked, including mixed records. DNS is revalidated before
reusing an idle HTTP connection, and the connected peer must belong to the current
answer set and configured address policy. TLS still validates the original
hostname against explicitly selected public or additional DER roots.

The guest may set only explicitly approved application header names. Host,
framing, hop-by-hop and credential headers are reserved. Content type and
idempotency key have bounded typed fields. Duplicates, invalid tokens, controls,
userinfo, fragments, unsupported schemes, backslashes and encoded path selectors
are rejected. URL normalization precedes policy evaluation; the exact normalized
path is sent. Queries are transmitted but cannot substitute for the path grant.

`HttpCredential` supplies trusted per-destination header values. Credential
storage is bounded and zeroizing; diagnostics never print it. Public configuration
digests exclude credential bytes. Credential changes require a new installed
epoch and matching bindings; an old session cannot select the replacement epoch.
The adapter has no ambient proxies, cookie jar, netrc, automatic authentication,
redirect-following library client or transparent retry middleware.

## Redirects, outcomes and deadlines

Redirect following defaults to zero and is capped at three hops. Only GET/HEAD
with an empty request body can follow 301/302/303/307/308 responses. Every next
origin must be configured and explicitly listed in the previous destination's
`redirectDestinations`, including same-origin redirects. Each hop consumes a new
outbound-request charge and passes a fresh policy/audit dispatch barrier. The
last allowed hop returns its HTTP status; mutations always return their redirect
status. No method is automatically retried, even with an idempotency key.

A cross-origin redirect clears all guest headers, media type and idempotency key,
and disables configured credentials for the rest of that chain. Redirecting back
to the first origin cannot restore credentials. The old response, call and input
owners are dropped before waiting for the next pool slot, including with one
running slot.

One monotonic deadline covers queueing, DNS, connect, TLS, request writes, response
headers/body, decompression and redirects. `timeout-millis` can only narrow it.
Typed errors distinguish invalid input, denial, exhaustion, DNS/TLS failures,
connection failure, cancellation, deadline expiry and uncertainty. Once HTTP bytes
may have reached a peer, a lost response is `uncertain`; cancellation cannot undo
that possible effect. A valid response header supplies `http-response-received`
audit evidence even if its body later fails or exceeds limits. HTTP success does
not imply an application transaction, consumer processing or durable outbox.

## Storage, ownership and limits

| Storage/work | Default provider limit | Hard profile bound |
| --- | --- | --- |
| Request body | 32 KiB | 512 KiB |
| Encoded response body | 32 KiB | 512 KiB |
| Decoded response body | 32 KiB | 512 KiB |
| Retained headers | 8 KiB, 32 fields | 32 KiB, 64 fields |
| Redirects | disabled | 3 |
| Additional roots | none | 8 DER values, 32 KiB total |

Broker input/output ceilings, I/O chunk/live-byte ceilings, provider metadata,
connection/concurrency quotas and canonical hostcall fuel independently intersect
these values. Increasing one limit does not increase the others. The HTTP/1.1
parser has a separately prepaid 32 KiB buffer bound. TLS, DNS parsing and protocol
objects have shared metadata reservations before construction; request body bytes
retain their original input owner through Hyper. TCP send/receive buffers request
16/32 KiB; operating systems may round those sizes. These counters are logical
ownership bounds, not a claim to measure every allocator or kernel RSS byte.

Identity, gzip and zlib `deflate` responses are supported. Encoded and decoded
storage, decoder windows and optional gzip header storage are reserved separately.
Decompression checks output capacity incrementally and yields between finite
chunks. Unsupported encodings, malformed lengths, conflicting framing, oversized
headers/trailers and decompression bombs fail within those bounds. Hop-by-hop
headers and encoded framing are removed from the returned decoded response.

The active future drives its real socket and HTTP connection directly. No detached
per-request worker can outlive cancellation. Fully consumed reusable connections
may enter the bounded shared idle pool only after request owners have gone;
otherwise they close. A completed audit or dropped response waiter is not proof
of cleanup. The Wasmtime adapter retains the affine call through canonical
lowering and Store destruction, so live call/result ceilings also bound repeated
calls from one activation. Waiting continues to own its execution cell.

## Validation and maintained capsule

The [HTTP probe capsule](../../examples/outbound-http/README.md) has maintained
WIT, a canonical async component generator and checked immutable package metadata.
It executes against the production Wasmtime backend with the real broker/provider.

```sh
cargo test -p latent-http --lib --locked
cargo test -p latent-capabilities --lib --locked
cargo test -p latent-wasmtime --test http --locked
```

Fixtures cover every method, known status versus uncertainty, actual TLS trust and
hostname verification, DNS cache/rebinding/TCP fallback, special addresses,
redirect credential stripping and fresh policy checks, malicious framing/lengths,
compression bounds, concurrent requests, idle reuse, cancellation and resource
recovery. Guest tests cover repeated warm-cell execution, denial, revoked plans,
missing providers, traps, cancellation and original-ledger finalization. Required
audit tests check both provider evidence and secret redaction. No load benchmark
or general hostile-multitenant qualification is implied by these functional tests.
Streaming HTTP remains the separate ABI/provider work in
[#212](https://github.com/KirilsTurkins/latent-service-fabric/issues/212).
