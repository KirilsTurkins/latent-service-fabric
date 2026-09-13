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
peer closure and admission rejection. The timers and authentication marker are
owned by the accepted connection and remain bounded by
`limits.maximumConnections`.

Authentication is still performed on every RPC. A successful first request only
ends the pre-authentication connection deadline; it does not create
connection-wide authority or bypass token/currentness checks on later requests.

## Established connection age and draining

`limits.maximumConnectionAgeMillis` defaults to `300000` ms. It must be at least
the pre-authentication timeout and at most `86400000` ms. Age is measured from
TCP acceptance and is never renewed by requests, successful authentication,
partial bytes, or HTTP/2 PING traffic. Authenticated idle connections are covered
by this absolute age policy; no separate idle reset heuristic is required.

At the age limit, dispatch rejects every new RPC with `UNAVAILABLE` and a
reconnect diagnostic. This includes new Cancel/GetActivation requests on the
draining connection. Clients can issue those requests on a fresh authenticated
connection; the existing global RPC reservation still applies, and it does not
reserve a separate TCP admission slot. Draining does not confer any exemption
from authentication or authorization.

Calls already admitted may finish within
`limits.connectionDrainTimeoutMillis`, which defaults to `5000` ms and accepts
`1` through `60000` ms. Their ordinary request/activation deadlines still apply.
At the end of the drain allowance, the connection is closed even if a caller is
not reading responses or an RPC remains pending. The I/O owner has an absolute
accept-time timer, and Tonic's independent connection driver has a finite
age-plus-grace timeout so protocol backpressure cannot disable final retirement.
This policy uses RPC admission for draining; it does not depend on a peer
acknowledging a keepalive or a GOAWAY exchange.

The socket is dropped before its connection permit. RPC bodies, control tasks
and underlying activation work retain their own charges until their actual
destruction or independently owned cleanup; closing a socket does not prove
that a remote effect was undone. A client that loses a mutation/invocation
response must use its retained operation/activation identity to inspect the
outcome, rather than blindly replaying an uncertain operation. Configure drain
allowance and application deadlines for the required completion window.

The saturating `expired_max_age_connections` snapshot counter counts owners
closed at or after their final age deadline, once per owner. Peer closure or
shutdown can race that deadline; the counter records observed retirement age,
not exclusive attribution to a particular timer. The pre-authentication counter
records a successful unauthenticated-to-expired transition. An expired or closed
connection cannot become authenticated through retained request metadata.

## Validation and availability boundary

The focused transport suite uses disposable loopback sockets, generated clients,
real RPC adapters and small controlled runtime fixtures. It covers two-slot
silent/partial saturation followed by a successful authenticated status call;
completed HTTP/2 negotiation and PINGs without credentials; rejected requests;
later valid and invalid credentials on the same connection; age-based rejection
of new calls; a held call finishing during drain; forced pending-call cleanup;
peer drop and node shutdown. A paused-clock state test covers exact first-auth
expiry and terminal-state behavior. Existing control-task/body ownership and
shutdown tests remain applicable.

These cases contribute transport evidence to
[#238](https://github.com/KirilsTurkins/latent-service-fabric/issues/238) and
[#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240).
Run `cargo test -p latentd --lib --all-features --locked standalone::transport`
for the focused suite. It is not a load benchmark or hostile-multitenancy
certification.

The listener remains loopback-only. A process sharing that network namespace
can still compete for fresh slots by continuously reconnecting. Finite residency
reclaims abandoned connections but does not promise fairness against sustained
admission floods or dedicated management availability. Protect local host/network
access accordingly; a protected local socket or separately authorized control
listener would need its own supported transport contract.
