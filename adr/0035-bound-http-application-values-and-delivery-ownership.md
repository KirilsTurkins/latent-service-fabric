# ADR-0035: Bound HTTP application values and delivery ownership

- Status: Accepted
- Date: 2026-09-15
- Related: [ADR-0012](0012-place-remote-invocation-behind-a-wit-native-transport-abstraction.md), [ADR-0028](0028-retain-activation-ownership-across-asynchronous-waits.md), [#222](https://github.com/KirilsTurkins/latent-service-fabric/issues/222)

## Context

Inbound browser requests need portable HTTP semantics independent of the
outbound HTTP provider. The legacy generic ingress metadata map loses repeated
fields. An application response also needs a retained delivery owner: a completed
activation does not prove that a transport has written its response.

The same application export can be called through generic RPC. Putting a
principal into its request payload would let an RPC caller fabricate that view.
The existing activation context already provides authenticated identity, trace
and deadlines independently of caller values.

## Decision

Introduce `latent:web/application@0.1.0` and its closed `buffered-v1` contract.
The `application-service` world imports the existing context interface and
exports an asynchronous `handle(request) -> response`. Guests obtain authority
from host context. Request fields and forwarding headers confer no authority.
Application async exports do not require an unrelated installed provider;
import recognition, configured providers and per-activation bindings remain
separate requirements.

Keep ordered, repeated HTTP fields and opaque field bytes. Normalize authority
and the request target once, before routing and security checks. Reject framing
ambiguities, forbidden hop fields, control-character injection and platform
metadata impersonation. HTTP statuses are ordinary application data; platform,
invalid-result and transport failures retain distinct meanings.

Select bounded buffering for this first application profile. Raw HTTP request
and response bodies are limited to 64 KiB and 256 KiB respectively. Their WIT
field is explicitly `body-base64: string`, using canonical padded RFC 4648
encoding. This avoids a generic runtime value per byte. It does not reinterpret
the existing `list<u8>` codec or put base64 on the HTTP connection. Header values
remain small bounded byte lists. Neither implicit decompression nor streaming,
trailers, protocol upgrade or application-owned listeners are selected.

Reserve shared exchange capacity before mapping allocations. Move one owner
through collection, invocation and delivery. Disconnects and deadlines signal
cancellation but do not refund surviving buffers or detach running activations.
Release actual data before returning its reservation. A delivery receipt requires
completed local header/body writes and does not claim peer consumption.

The [protocol reference](../docs/protocol/http-applications.md) fixes the exact
limits, rejection rules, generic value-codec settings and failure mapping.
Runtime/guest memory and transport socket/TLS buffers keep independent ownership
and limits; the mapping reservation is not a process-RSS guarantee. Existing
Phase 1 codec defaults are unchanged. Nodes must explicitly select compatible
finite runtime settings when enabling this application profile.

## Consequences

The portable contract, generated bindings, codec and ownership tests are used by
the shared listener in [ADR-0039](0039-bound-the-shared-http-listener-and-preserve-selected-admission.md)
and durable routes in [ADR-0036](0036-publish-http-triggers-with-exact-catalog-target-pins.md).
These implementations retain normal admission, exact publication/revision pins,
tenant policy and cancellation cleanup. A WIT declaration alone installs no
listener or provider.

The initial restrictions are a versioned profile, not a permanent interoperability
ceiling. Streaming or larger bodies require an explicit compatible contract,
bounded owners and conformance evidence. Fresh activations and the absence of
dormant service-owned execution resources remain unchanged.
