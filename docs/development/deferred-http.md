# Qualified deferred HTTP delivery

The `qualified-http-effect-v1` adapter implements one operator approved
`lsf-atomic-idempotent-http-v1` endpoint contract. It reuses the installed buffered
`HttpProvider`, its exact TLS configuration, destination checks, protected opaque
authorization binding and shared `ProviderPools`. It creates no guest activation,
network driver, provider pool or production storage engine.

## Closed operation contract

The protected configuration binds format version 1, one HTTPS origin with static
approved addresses, one canonical POST operation path and one canonical GET lookup
prefix. The endpoint incarnation is 64 lowercase hexadecimal characters. Retention
is between 1 second and 7 days, and the immutable body is at most 64 KiB. The media
type is exactly `application/octet-stream`, `application/json` or `text/plain`.
Payload metadata is empty. Redirects, compressed replies, streaming providers,
dynamic DNS and client selected destinations are rejected before dispatch.

Every attempt first sends GET to the operation path. The endpoint must return
HTTP 200 and exactly this bounded JSON shape:

```json
{
  "formatVersion": 1,
  "contract": "lsf-atomic-idempotent-http-v1",
  "endpointIncarnation": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "retentionMillis": 10000,
  "maximumPayloadBytes": 8192
}
```

The profile and every receipt use `Content-Type: application/json`,
`Lsf-Endpoint-Contract`, `Lsf-Endpoint-Incarnation` and
`Lsf-Idempotency-Retention-Millis` headers matching the configuration. Missing,
duplicate, malformed or incompatible fields fail closed. JSON replies are at most
2048 bytes and four levels deep; unknown or duplicate JSON fields are rejected.
Any `Location` header or nonidentity content encoding is rejected.

The first business operation is POST to the approved path with the exact stored
body bytes. Its `Idempotency-Key` is `lsf-effect-` followed by the immutable
64-character effect ID. `Lsf-Body-Sha256` is the SHA-256 of those bytes. The original
media type, endpoint contract, incarnation and retention headers are preserved.
Authorization comes only from the installed opaque protected binding. It is
checked again after TLS connects and immediately before HTTP writes; credentials
never appear in the durable payload or provider receipt.

The endpoint must atomically compare its current incarnation and idempotency
record with the business mutation. An absent key creates both the mutation and
receipt in one durable transaction. Equal key and body digest return the original
sequence without another mutation. Changed body returns conflict. The endpoint
retains the record for its promised horizon and serializes endpoint replacement
and older backup restore against dispatch; a profile probe alone cannot prove
continuity after arbitrary endpoint rollback.

Receipts have exactly `formatVersion`, `endpointIncarnation`, `idempotencyKey`,
`bodyDigest`, `outcome`, `sequence` and `duplicate` fields. Accepted POST replies
are HTTP 200 or 201 with a positive sequence. A qualified HTTP 422 rejection has
sequence zero, the exact digest and no mutation. Other HTTP errors or malformed
replies after possible POST writes remain uncertain. The retained provider receipt
contains only the endpoint incarnation, sequence and duplicate flag.

## Recovery and physical ownership

No irreversible HTTP operation runs before the state/result/payload/outbox/due
envelope commits. Each provider attempt owns its original finite slot, input and
protocol charges until its real payload, headers, socket and reply are destroyed.
The existing transport drives HTTP in that original future; it spawns no detached
connection task. Cancellation during TLS or reply reading closes the actual
socket before the slot is refunded. A shutdown cutoff reports live ownership and
quarantine while a request remains physically owned.

Accepted namespace closure disables every exact tenant/namespace/incarnation
rule under the same metadata fence used by the held grant's prewrite check. The
close is sticky for that incarnation, including across a later publication;
rejected original management acceptance leaves the old rules current. Closure
does not refund a live request or declare its physical cleanup. The provider's
original request owner is the last attempt field destroyed, after its actual
payload and attempt metadata.

A possibly sent first POST can schedule one bounded recovery attempt, subject to
the captured attempt ceiling and original horizon. That attempt sends GET to
`lookupPrefix + idempotencyKey`, preserving the exact digest and incarnation. It
never sends POST. HTTP 200 with a matching accepted receipt confirms the original
mutation. HTTP 404 absent, HTTP 409 conflict, HTTP 410 expired, or an ambiguous
lookup leaves explicit uncertainty without another automatic operation. The
client horizon is the earlier of the original effect expiry and original commit
time plus approved retention; reconnect does not extend it.

The authenticated management adapter also performs only profile GET and lookup
GET. Its positive confirmation retains the exact original persisted provider
attempt and supported effect-row version. The host management writer still must
validate current operator authority, actual physical retirement and that exact
row/version before recording a disposition. Absence is never a proof of
nonexecution, and generic HTTP redrive remains denied.

Fresh management lookup has sealed `ReconcileOnly` purpose. It can inspect the
original receipt after execution revocation or expiry when current management
permission, the exact retained profile and protected credential remain valid.
It preserves the original execution expiry as provenance; it does not renew
execution or authorize POST. The status horizon remains original commit time
plus the approved endpoint retention, intersected with the original finite
management deadline. Ordinary adapter acceptance rejects lookup-only grants
before provider admission or application buffer construction.

Lookup admission uses the existing provider maintenance/cleanup ledger rather
than ordinary running/request slots. One finite request owns its metadata and
protocol-operation allowance through actual socket destruction, including after
the caller drops its request. It uses the same client, credential epoch, pool
and connection limits; it cannot borrow an idle guest connection or create a
second pool. Exhausted cleanup, shared metadata, live connection, or active
dial/backoff capacity remains an explicit bounded unavailable/uncertain result.

## Standalone factory

`providers.http.deferred` is optional and contains at most 16 distinct
`QualifiedHttpEndpoint` entries. It requires exactly one protected `authorization`
credential binding for destination zero. `ProviderRuntime::deferred_http_adapters`
constructs adapters from the same installed immediate provider and trusted
`EffectTimeSource`; it installs no second client. `HttpEffectAdapter::rule` returns
the exact immutable profile and protected reference for a current approved scope.
Publishing that rule remains a current-policy decision. Its response ceiling must
cover at least 22,528 bytes of bounded reply/header/container storage.

## Measured native evidence

Pinned Rust 1.97.1 Linux ran all 56 HTTP library cases: 56 passed, zero failures,
ignored or filtered cases. Strict all-target/all-feature HTTP Clippy, standalone
all-feature compilation and strict standalone library Clippy passed. The shared
effect library passed all 89 cases without ignored or filtered cases. The
16 deferred cases use the actual protected host engine, captured intent writer,
state session, namespace/current effect fences, fixed dispatcher, protected
credential store, bounded provider pools and real TCP/TLS transport.

The maintained reference endpoint has one bounded listener and its own protected
finite test store. Counter, receipt and incarnation expectations share one actual
atomic writer. A separate TLS failure proxy forwards the real request and reads
the endpoint's real reply before injecting loss, malformed/oversized replies,
HTTP errors or redirects. Test gates observe actual TLS or postmutation reply
ownership; deadline timeouts are watchdogs, never physical-abort evidence.

The tests inspect durable counter and receipt rows for normal commit, presend
restart, lost response, equal-key replay, changed-body conflict, absent/expired
lookup, qualified rejection, endpoint recreation, credential rotation, current
revocation, cancellation and live shutdown. Rejected/positively aborted commands
commit no HTTP intent or remote mutation. A lock-order case uses the actual
protected command role and effect acceptance fence to reject clock observation
inside synchronous adapter acceptance.

The namespace-close schedule holds an accepted original grant at the actual
second TLS handshake. Accepted metadata closure blocks the later business write
and cannot re-enable the old incarnation through a new publication; rejected
original acceptance permits the unchanged grant to complete. Both branches
observe the actual request and physical context before closure and await their
positive retirement afterward. This exercises the reviewed effect invalidation
bridge directly; the authenticated Policy/Namespace/Native management acceptance
has its separate maintained Wire schedules.

The fixture contract is version 1, with a 10-second retention and 8192-byte body
limit. Its endpoint source Git blob is
`ccb4b97cd853ff1a1ad865ed1e22c9939b4c94be`; the controlled proxy source blob is
`814b5cf4d1af413764059b7acc13c26ac834c293`. These fixtures are compiled and run by
the registered HTTP library suite; they require no external account or broker.

This evidence uses trusted synthetic source identity labels. Verified guest and
ordinary standalone transaction composition and authenticated management
qualification remain separate integration work. The reference endpoint proves
this closed contract under its stated administration assumptions. It does not
certify commercial APIs, arbitrary HTTP mutations or endpoint rollback safety.

The lookup-purpose follow-up passed all 59 HTTP, 145 capability, 106 effect and
118 state library cases on pinned Rust 1.97.1 Linux, with no ignored or filtered
cases. Strict HTTP/capabilities/effects/state all-target/all-feature Clippy passed.
The capability running-call allocation remains within the original prepaid
2048-byte operation metadata allowance and retains its affine call through
actual retirement. Three new
real-TLS schedules exercise expired and revoked execution with an exact positive
original receipt, absent/recreated/expired status, and current lookup revocation
while the actual TLS socket is held. The extended proxy source for this
follow-up is Git blob
`2f1acd68eb31a06aa27dbe4ce8589961c41cbb73`.
The positive schedule fills the original
shared native ordinary slots and provider running slot while its same-owner
recovery pin and maintenance request complete. Two real-TCP pool schedules prove
bounded operation counts, metadata/socket retention after caller drop, and the
explicit unavailable boundary when a live ordinary connection occupies capacity.
These provider-purpose schedules use a controlled current authorization gate;
the production authenticated Wire management path has its separate qualification.
