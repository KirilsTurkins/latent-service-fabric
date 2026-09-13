# Standalone transport connection deadlines

The standalone loopback listener bounds accepted TCP connections independently
from activation and RPC quotas. An accepted connection owns one connection slot
before HTTP/2 negotiation or bearer authentication begins, so pre-authentication
residency must also be finite.

## Pre-authentication deadline

`limits.unauthenticatedConnectionTimeoutMillis` defaults to `5000` ms and accepts
values from `100` through `60000` ms. The node starts one monotonic deadline when
it accepts the TCP connection. The deadline is not renewed by partial HTTP/2
bytes, protocol traffic, or rejected authentication attempts. It stops applying
only after one RPC has supplied a configured bearer credential and completed the
normal per-request authentication path before the original deadline.

Expiry closes the owned TCP stream before its connection guard is released. The
transport snapshot increments `expired_unauthenticated_connections` once for an
expired owner, so tests and node composition can distinguish expiry from ordinary
peer closure and admission rejection. The timer and authentication marker are
owned by the accepted connection and remain bounded by
`limits.maximumConnections`.

Authentication is still performed on every RPC. A successful first request only
ends the pre-authentication connection deadline; it does not create
connection-wide authority or bypass token/currentness checks on later requests.

## Current boundary

This #277 delivery slice reclaims silent and incompletely negotiated connections.
It does not yet define the established authenticated idle/maximum-age policy,
drain semantics for long-running RPCs, or the complete rejected-authentication
and trickle-traffic conformance matrix tracked by
[#277](https://github.com/KirilsTurkins/latent-service-fabric/issues/277).
Reclaiming abandoned sockets also does not prove fairness against a process that
continuously reconnects on the local loopback interface.
