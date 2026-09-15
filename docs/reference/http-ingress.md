# Shared HTTP application ingress

The standalone Linux node can run one optional HTTP application listener beside
its authenticated loopback management/invocation RPC listener. Every route uses
the same node admission, scheduling, reusable cells, fresh Wasmtime activation
state and cancellation machinery. Dormant deployments create no network owners.

This implements #229 and [ADR-0039](../../adr/0039-bound-the-shared-http-listener-and-preserve-selected-admission.md).
The application export is the public async
[`latent:web/application@0.1.0`](../protocol/http-applications.md) `handle` function.
[HTTP triggers](http-triggers.md) bind canonical host/path/method matches to exact
tenant-scoped publications and deployment revisions. Angular adaptation and
web-package deployment/asset integration remain #233, #226 and #231; enabling
this listener does not install those later adapters.

## Configuration

Omit `httpIngress` to create no HTTP listener, connection task or exchange pool.
Explicit null, unknown fields and unsupported profiles are rejected. The closed
[configuration schema](../../schemas/node-http-ingress.schema.json) defines
individual limits; native derivation also validates relationships and authority.

Add the following members to an existing node configuration, including a real
invoke-role credential for the target tenant. The node-wide payload limit must
be explicitly raised to 2 MiB for the buffered application value frame. Other
node settings, the actual request/response body limits, and deployment grants
still apply.

```json
{
  "limits": {"maximumPayloadBytes": 2097152},
  "httpIngress": {
    "formatVersion": 1,
    "bind": "0.0.0.0:8443",
    "transport": {
      "mode": "tls",
      "certificateFile": "tls/server.pem",
      "privateKeyFile": "tls/server-key.pem"
    },
    "authentication": {"mode": "bearer"},
    "limits": {
      "maximumConnections": 32,
      "maximumExchanges": 8,
      "maximumBufferBytes": 50331648,
      "handshakeTimeoutMillis": 2000,
      "headerTimeoutMillis": 2000,
      "bodyTimeoutMillis": 5000,
      "idleTimeoutMillis": 5000,
      "writeTimeoutMillis": 5000,
      "maximumConnectionAgeMillis": 60000,
      "maximumRequestsPerConnection": 100
    }
  }
}
```

TLS uses TLS 1.3 and HTTP/1.1 ALPN. It accepts a PEM certificate chain of at most
64 KiB/eight certificates and one PEM private key in a file of at most 16 KiB.
Paths loaded from JSON are relative to that configuration's parent. Opened-file
and ancestor checks enforce certificate integrity and private-key secrecy;
symlinks and insecure replacement paths fail. Keys are never included in Debug
or error output. Early data, session tickets, session storage and certificate
compression are disabled in this initial profile. Configuration is fixed for
the node lifetime; replacement requires an orderly restart.

For local development, use `"transport":{"mode":"loopback"}` and a loopback
bind, for example `127.0.0.1:8080`. Both bind and peer must be loopback. It is
explicitly cleartext. For a TLS-terminating reverse proxy, use
`"transport":{"mode":"trusted-proxy","peers":["127.0.0.1"]}`. Only listed
numeric peer addresses may connect, and the external scheme is fixed to HTTPS.
The proxy-to-node link must be secured by deployment networking. This profile
does not authenticate a proxy by an arbitrary forwarded header.

Direct connections with Forwarded or X-Forwarded-* fields are rejected. An
approved proxy may attach them, but they are discarded entirely; they cannot
override Host, principal, tenant, trace or deadline. The node validates the
application Authorization itself. The proxy must preserve the intended Host and
sanitize its incoming transport headers. No DNS lookup, CIDR expansion or
automatic trust of loopback proxy identity occurs.

## Principal adapters

`bearer` accepts one bounded Authorization bearer token from the node's configured
**invoke-role** credentials. Administrator/operator tokens are excluded. Each
keepalive request authenticates independently and must match the selected
route's tenant. The guest receives the resulting principal through host context;
Authorization is absent from its application headers.

An intentionally public site may instead select this explicit adapter:

```json
{
  "mode": "public-origins",
  "origins": [
    {"authority": "www.example.test", "subject": "public-web", "tenant": "examples"}
  ]
}
```

Use it as `httpIngress.authentication`. Each canonical authority is unique;
the tenant must already exist in node credential configuration. The configured
subject becomes a Trigger principal with no service or administrator claims.
Host matching never lets that principal enter another tenant. An Authorization
header under this adapter is rejected instead of silently switching identities.
Public origins deliberately allow unauthenticated network callers to invoke
their authorized routes; they are unsuitable for private application routes.
Application cookies remain data and must be verified by the application when
application sessions are needed.

## Ownership and bounds

| Owner / boundary | Bound and retirement |
| --- | --- |
| Shared listener / driver | One each when enabled; no application-owned task. |
| Accepted connections / OS listen backlog | Configured 1–128 connections and a backlog of that size. Excess accepted sockets close immediately. |
| TLS handshake input / TLS buffering | At most 64 KiB encrypted input before handshake completion; 64 KiB configured connection buffer limit; absolute handshake deadline. |
| Raw head / mapped headers | 32 KiB head including request line; 64 fields and 16 KiB aggregate name/value bytes before mapping. |
| Raw request / response body | 64 KiB / 256 KiB, unchanged `buffered-v1` limits. |
| Connection reservation | 512 KiB conservative user-space allowance before TLS/parser allocation; retained through stream destruction. |
| Exchange reservation | 4 MiB per live collector, invocation, cleanup retention or delivery; maximum 1–64 exchanges, also capped by node activation capacity. |
| Aggregate buffer ceiling | At most 512 MiB configured; must cover all configured connection plus exchange reservations. This is an ownership allowance, not process RSS. |
| Ingress wait queue | Zero; pool exhaustion returns 503 or closes a connection whose response cannot be written. |
| Admitted scheduling | Existing node/tenant/cell-class queue, quota and cleanup-slot limits; no second ingress work queue. |
| Native guest/value allocations | Existing activation/runtime owners; HTTP explicitly selects the 2 MiB value frame, 32,768 nodes, 512 KiB strings, 64 MiB lifted-value ceiling and 2 MiB hostcall-fuel profile. The engine identity includes these settings. |

Kernel socket buffers are requested at 16 KiB send and 64 KiB receive before
listening, so accepted sockets inherit them before TCP window negotiation.
See [Linux TCP buffer configuration](https://man7.org/linux/man-pages/man7/tcp.7.html).
Platform rounding and kernel overhead remain outside the user-space reservation. Shared
TLS configuration and cryptographic/runtime implementation allocations are not
a claim of a hard whole-process memory ceiling. Keep the
[execution security profile](../runtime/execution-security-profiles.md) appropriate
to admitted guests; TLS transport does not replace enforced admission or compiler
isolation.

The first-byte wait is bounded by the header timeout, and subsequent keepalive
idle waits by the idle timeout. Once a first byte arrives, one absolute header
deadline covers the rest of the head. Body collection and response delivery each
have an absolute deadline that does not reset when a byte makes progress.
The request's node execution allowance starts at first-byte observation and is
intersected with the connection's absolute age. Header/body collection, admission,
preparation and scheduling cannot renew it. Early rejection responses and final
TLS shutdown have a bounded transport write grace, capped by connection age;
that grace never renews an activation's budget or permits new work.

The listener preserves the exact revision and immutable policy view captured
at HTTP selection. It never hashes the new activation ID to choose another
weighted candidate. A concurrent deployment change may leave the accepted
request on its captured revision; new requests reject a stale exact trigger
until its operator updates the target. Revocation/current publication authority
is still checked at admission and guarded execution start.

Disconnect or request expiry transfers the activation and its input/route owners
into the existing bounded cleanup driver. Permits return after those objects
are destroyed. Responses retain their delivery owner through header writes,
body writes and TLS flushes. Shutdown first stops accepting work, then drains or
cancels owners and joins the driver. A failed/aborted join cannot report a clean
HTTP shutdown.

## Protocol and failure behavior

The initial profile supports sequential HTTP/1.1 keepalive, Content-Length-framed
buffered requests, and the existing method/response restrictions. The listener
consumes one Connection header containing exactly `keep-alive` or `close`;
duplicates, comma lists and arbitrary field nominations fail. It requires CRLF,
rejects duplicate Host/Content-Length, and never combines fields. HEAD has no
body. Trailers, chunked coding, upgrades, HTTP/2, Expect/100-continue and streaming
are outside this version. No connection is reused after malformed framing.

Early pipelined bytes and EOF, including a write-half-close while awaiting an
activation, cancel that activation and close the connection. Clients must keep
the request side open until they receive the complete response. Idle, input,
request or write expiry closes the connection without an error response. Early
bounded rejections include 400/401/403/404,
413/417/431 or 503; invalid guest responses/traps map to 502. Error responses do
not reflect input, tokens or private runtime diagnostics.

Completed writes describe local transport acceptance. They do not prove browser
receipt, rendering or external-effect completion. A disconnect can occur after
the guest started; do not automatically retry an operation whose external result
is uncertain. This listener adds no transaction, outbox or exactly-once semantics.

## Observations and validation

Inventory exposes `http-listener`, `http-owner`, `http-connections`, `http-exchanges`
and `http-buffer-reservations`, using actual owner counts. The node descriptor
includes `lsf.http.endpoint` and `lsf.http.profile`. The native embedding API exposes
`http_endpoint()` and `http_snapshot()`; the optional HTTP shutdown report must
show joined owners, no live connections/exchanges and zero retained reservations.

Ordinary Rust tests exercise real sockets, framing/credential rejection, silent
and trickling peers, TLS handshake and post-handshake inactivity, proxy peer
restriction and recovery. Contract CI builds the small public web component and
runs the `actual_http_component` tests through real catalog publication, HTTP
triggers and Wasmtime. They cover tenant/principal reuse, maximum bodies, guest
failure, saturation, cancellation, slow input/output, exact selection across
cutover, revocation, public-origin identity, deadline and forced shutdown,
failed-startup reclamation, protected TLS keys and restart. These are bounded conformance tests, not a load
benchmark or Angular qualification claim.
