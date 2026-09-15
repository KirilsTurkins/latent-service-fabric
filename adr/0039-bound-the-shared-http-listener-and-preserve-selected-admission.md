# ADR-0039: Bound the shared HTTP listener and preserve selected admission

## Status

Accepted; Phase 3 #229. Extends ADR-0005, ADR-0006, ADR-0011 and ADR-0036.
Supersedes ADR-0035 only where its blanket Connection-header rejection applies
to the network listener: this listener consumes one strict `keep-alive` or
`close` option before the unchanged application mapper sees a `RawHead`.

## Context

Application types and durable trigger metadata do not own network connections.
A public listener needs finite pre-authentication residency, bounded parsing,
authenticated tenant selection, and actual response-write ownership. RPC handler
timeouts alone do not reclaim a silent socket. A second route lookup after HTTP
selection can also choose a different weighted revision or deployment generation.

## Decision

Install at most one optional node-owned application listener. Its initial
`buffered-http1-v1` profile supports HTTP/1.1 with sequential keepalive and either
TLS 1.3, explicit loopback cleartext, or an explicit trusted-proxy peer allowlist.
The proxy profile fixes the external scheme to HTTPS; forwarded fields never
select identity, authority, tenant or deadline. Direct peers supplying forwarded
metadata are rejected. Approved proxies must secure the proxy-to-node network
path and preserve the intended Host and application Authorization fields.

Authenticate every request with configured invoke-role bearer credentials or an
explicit public-origin identity. Public origins bind a canonical authority to a
tenant and low-privilege Trigger principal. They have no administrator claims.
Cookies, request data, trace headers and user-controlled identifiers do not create
LSF authority. Normal tenant, deployment and capability policy still applies.

Bound connection count, backlog, TLS input/buffering, header/body size, request
count and connection age. Use absolute handshake, header, body, idle and write
deadlines. A fixed connection reservation precedes parser/TLS allocation; a
separate shared exchange reservation precedes mapping. There is no ingress wait
queue: full pools reject immediately. Admitted work uses the existing finite
node scheduling queue and the original ingress deadline.

Preserve the exact accepted HTTP revision and its immutable policy catalog via
trusted native selected admission. Do not re-resolve with a new routing key.
Admission still validates the complete tuple and current publication permission;
the backend retains its guarded activation-start boundary. Keep the trigger
read lease through activation cleanup.

One bounded task owns each active connection. A dropped request transfers the
same activation, mapping bytes and route lease into the node's existing reserved
cleanup driver. No detached request tasks or replacement useful-work budgets are
created. Socket/TLS destruction precedes connection refund; response ownership
survives actual writes and TLS flushes. Completed writes mean local transport
acceptance, not browser receipt or processing.

The initial profile rejects chunked bodies, upgrades, streaming, HTTP/2, arbitrary
Connection nominations and early pipelining. A client write-half-close is treated
as disconnect during execution. These are versioned interoperability limits,
not new permanent restrictions on the fabric model. See the
[operator contract](../docs/reference/http-ingress.md) for exact limits and tests.

## Consequences

Dormant applications acquire no listeners, processes, event loops or guest state.
The shared fixed listener and bounded active owners appear in node inventory and
must be joined during shutdown. Compiler isolation, admission and provider trust
remain independent security boundaries. Existing execution security profiles
remain authoritative; enabling TLS does not qualify hostile guest execution.

Web-package routing, Angular adaptation, assets and hydration remain the
separately scoped #226, #233, #231, #232 and #234 integrations. HTTP requests use
immediate invocation semantics and receive no automatic retry or durable-effect
guarantee from this listener.

## References

- [RFC 9112 connection management](https://www.rfc-editor.org/rfc/rfc9112.html#section-9)
- [RFC 9110 Connection semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-7.6.1)
- [Bounded application mapping](../docs/protocol/http-applications.md)
- [Exact durable HTTP triggers](../docs/reference/http-triggers.md)
