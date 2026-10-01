# Deferred JetStream delivery

The `nats-jetstream-effect-v1` profile reuses the installed immediate
`NatsPublisher`, its TLS/authentication implementation, protected credential
references and original `ProviderPools`. A dispatcher supplies only an affine
sealed `DispatchGrant` and its exact `PayloadRecord`. No activation session or
application cell is fabricated. The immediate publisher still performs one
publication and never inherits deferred retries.

An effect maps to the approved tenant/topic, stream and exact subject. The
message ID is `lsf-effect-` followed by its 64 lowercase hexadecimal effect ID.
The payload bytes move into the attempt without another body copy. Media and
attributes are checked against the sealed canonical digest, encoded by the
maintained event framing and preserved on retries. This version selects
unordered delivery; ordering attributes are rejected rather than silently
promising a predecessor or global order.

Each attempt retains the shared tenant/provider/running request reservation,
input capacity and finite protocol scratch until the actual socket future and
buffers retire. Successful acknowledgement may transfer a verified socket to
the charged shared idle pool. There is no detached protocol driver. The sealed
original expiry/deadline limits the query and publish together, with at most two
network operations. Provider rotation and protected secret currentness are
checked by the existing owners. Accepted publication failures after a possible
write remain uncertain unless the maintained decoder supplies a definite
negative reply. A broker acknowledgement means broker acceptance, not consumer
processing or a database transaction inside NATS.

## Qualified duplicate horizon

A trusted `JetStreamQualification` binds format version 1, exact TLS INFO
software version, canonical UTC `stream.created`, bounded message/byte/age/size
limits and the configured duplicate window. Before every business publication,
the adapter queries the exact stream through the same authenticated connection.
Only file storage, one replica, limits retention and discard-new are supported.
Delete/purge are disabled; age eviction must cover the duplicate window.
Rollups, transforms, republish, mirrors/sources, per-message TTL, atomic batch,
counter and scheduled-message features are rejected. Every qualified field and
all mapped subjects must match. An incompatible retained decoder/profile cannot
redirect old effects to a new stream.

The conservative retry horizon starts at the original durable commit timestamp,
not at a later reconnect. Retry keeps the exact sealed effect/payload and stream
creation identity, uses checked 100/200/400/800 ms delay, the original finite
attempt ceiling and the earlier of expiry or duplicate horizon. The dispatcher
persists each explicit retry. Unproven/backward time, expiry, profile change or a
retry outside that horizon stops publication for reconciliation.

NATS documents message-ID deduplication and expected-stream checks in its
[JetStream reference](https://docs.nats.io/reference/2.12/jetstream). The
expected-stream header identifies a stream name; it is not an atomic creation-
identity fence. Operators must serialize stream replacement and older backup
restore against active dispatchers and reconcile uncertain history before
resuming. The probe plus immutable qualification is conservative evidence under
those explicit administration assumptions, not a permanent exactly-once
consumption guarantee or tolerance of arbitrary broker rollback.

## Standalone configuration and factory

`providers.events.deferred` is optional and has at most 16 unique entries:
`{ "topic": "orders", "qualification": { ... } }`. Each topic must already
belong to the installed immediate provider's tenant/mapping. Qualification is
validated before installation. `ProviderRuntime::deferred_event_adapters`
constructs the approved adapters from that same installed owner and a single
trusted `EffectTimeSource`. `JetStreamEffectAdapter::rule` supplies the exact
profile and protected reference for a current-policy approved binding; creating
this metadata does not authorize its publication in the current rule owner.
The transaction runtime supplies the same protected store and dispatcher.

## Measured implementation evidence

Pinned Rust 1.97.1 Linux: capability library 126/126, effect library 52/52 and NATS
library 8/8 passed, with no ignored cases. These include actual TCP retirement,
wrong-provider denial, finite operation counts, tenant capacity, provider
rotation and closed qualification decoding. Strict all-target NATS/effects
Clippy passed. Existing capability Clippy diagnostics are recorded separately;
they are not replaced by these test results.

The existing pinned broker image
`nats@sha256:065e8355c20a5575b3c77224be1855e8103fd148b68fba05130b9b8ddfa40ccc`
was actually launched and reported NATS 2.14.6. This is a software identity check,
not the completed real-broker campaign. State-to-broker commit, guest rejection,
restart, lost acknowledgement, broker-message inspection and live shutdown
qualification are still required before issue #392 can close. Protocol peers
and these library cases do not substitute for that campaign.
