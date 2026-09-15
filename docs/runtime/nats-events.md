# Bounded NATS JetStream publication

The `latent-nats` crate implements the configured `nats-jetstream-publish-v1`
profile for `latent:events/publisher@0.2.0`. It performs immediate publication
under [ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md). A synchronous guest
call cooperatively awaits its original activation-owned I/O; no execution or
control thread blocks on a broker response.

## Supported transport and authority

The conformance server is NATS **2.14.6**, pinned to the Linux amd64 image
`nats@sha256:065e8355c20a5575b3c77224be1855e8103fd148b68fba05130b9b8ddfa40ccc`.
The tested composition uses Linux x86_64 and the protected local credential store.

`NatsConfig` admits one explicit IPv4 socket and a separately verified TLS server
name. Non-public peers require an explicit opt-in for that exact address. IPv6,
DNS, proxies, discovered servers, redirects, automatic reconnect loops and
plaintext fallback are outside this initial profile. The server must enable
`tls.handshake_first: true`: INFO and credentials are exchanged inside TLS.
Compiled public certificate roots and bounded operator-supplied DER roots are
explicit configuration choices. TLS key logging, early data and session
resumption are disabled. See the upstream [TLS configuration](https://docs.nats.io/learn/security/encryption)
and [client protocol](https://docs.nats.io/reference/protocols/client).

An operator maps each `(tenant, guest topic)` to one exact subject and expected
stream. Guest topics cannot contain wildcards or system/inbox prefixes. Two
tenants cannot map the same physical subject in one configuration. The broker
independently authorizes the guest's logical topic against the current compiled
plan after queue admission. It never treats the guest topic as a broker URL,
subject, username or stream-management command.

Each configured tenant supplies a `NatsCredential`: an optional fixed username
and an opaque `TlsProviderCredential`. A username selects password authentication;
its absence selects token authentication. `LocalSecretStore::bind_tls_credential`
checks a separate `SecretPurpose::TlsProviderCredential`, tenant, provider ID and
TLS protocol/name/port destination. HTTP credentials and guest-readable values
cannot substitute for that purpose. Password/token bytes are resolved after
queue admission, kept in zeroizing authentication buffers and never exposed to
WIT, configuration digests or status. The store's expiry/rotation checks run again
immediately before the possible publication write. A connection authenticated
with different current material is destroyed before reuse. A rotation after that
start boundary cannot undo the already accepted operation.

For user/password authentication, the broker user needs publication permission
only for the mapped subjects and subscription permission for `_INBOX.LSF.>`.
Each provider instance generates a random reply-inbox namespace and uses a
monotonic per-operation suffix. A reply must match that exact inbox, subscription
ID and expected stream. LSF does not provision streams or use `$SYS`/`$JS` APIs in
this adapter; the separately bounded test fixture provisions its own streams.

## Receipts, failure and duplicate scope

A successful receipt contains the validated stream name, positive sequence and
broker-reported duplicate flag. `event-id` is `stream:sequence`, scoped to the
selected broker; it is not a globally unique application identity.
`accepted-at-unix-millis` records LSF's local observation time, not a server
persistence timestamp. Receipt validation follows the pinned server's
[publication acknowledgement definition](https://github.com/nats-io/nats-server/blob/v2.14.6/server/stream.go).

Acknowledgement means the broker accepted the publication according to that
stream's storage/replication configuration. It does not mean consumer processing,
application commit, durable disk sync in every configuration or end-to-end
exactly-once delivery. There is no application transaction, outbox or workflow
coupling.

| Observation | Guest outcome |
| --- | --- |
| Invalid topic/event, missing grant or exhausted budget | Explicit rejection before publication |
| Connection/TLS failure before a possible publication write | Unavailable; cancellation/deadline retains its own error |
| Exact broker publish-permission refusal | Permission denied |
| Validated no-responders status or selected 4xx broker rejection | Bounded known failure |
| Positive acknowledgement for the selected stream | Receipt, including duplicate status |
| Lost connection, cancellation, deadline, malformed/foreign reply after a possible write | Uncertain |
| Internal/storage error whose effect cannot be established | Uncertain |

Cancellation stops local work and closes its socket; it cannot retract a possible
remote effect. A guest may observe the typed `uncertain` result before its epoch
interruption, or be interrupted by cancellation. Audit preserves the provider's
observed acknowledgement/uncertainty separately from guest delivery. No uncertain
publication is automatically retried.

The adapter sends `Nats-Expected-Stream` and a length-delimited SHA-256
`Nats-Msg-Id` derived from the configured idempotency namespace, tenant, logical
topic and caller key. Attributes are emitted only under `Lsf-Attr-`; they cannot
override those reserved fields. Payload and attributes are not part of the
idempotency identity: callers must not reuse one key for different intended
operations. Different tenant/topic/namespace identities do not share a key.

`duplicate_window_millis` records the required operator stream setting (1 second
to 24 hours); this adapter does not query or enforce remote stream configuration.
The operator must configure it consistently. There is no local deduplication
cache. Repeated keys can be accepted again after the actual broker window expires,
a stream is recreated, or its retained deduplication state is lost. Tests exercise
the real one-second stream window and explicit caller retries after a lost reply.

## Resource ownership and limits

| Resource | Profile bound |
| --- | --- |
| Mappings / configured tenant credential slots | At most 16 of each |
| Logical topic / subject / stream | At most 128 ASCII bytes each |
| Payload | Explicit operator maximum, at most 256 KiB |
| Key / idempotency key | At most 256 bytes each; idempotency key required |
| Media type | At most 128 bytes |
| Attributes | At most 16; name/value at most 64/256 bytes; aggregate bounded |
| Encoded headers | At most 4 KiB |
| Token/password | At most 4 KiB; authentication scratch prepaid |
| Control line / received receipt frame | At most 8 KiB / 4 KiB |
| JSON nesting / control frames per protocol stage | At most 8 / 8 |
| Original operation timeout | Explicit 10 ms to 30 seconds, narrowed by activation deadline |
| TLS/parser state | Separate 256 KiB shared reservation per physical connection |

Input length and retained capacity are checked before retaining a queued future.
I/O staging quotas cover the actual typed input and the 32 KiB per-call encoding
workspace. A high payload limit also requires a sufficiently large shared I/O
chunk limit; the default chunk size remains 64 KiB. Receipt/lowering capacity is
reserved at guarded dispatch and stays with `EventCompletion::owner` through
canonical lowering and Store destruction. Discarded futures close actual sockets
before returning their connection charges. These are explicit accounting bounds,
not a claim about whole-process RSS or allocator overhead.

Every admitted publish attempt consumes **one outbound request**, including a
broker-reported duplicate. `effectCount` remains reserved for the later durable
intent model. A refused atomic budget reservation opens no connection. Queue,
connection, authentication, subscription and acknowledgement waits all retain
one original deadline. Shared [provider pools](provider-pools.md) bound running
and queued calls, client/connection counts, metadata, idle age and dial backoff.

A checked reusable connection is parked without an activation owner. It handles
bounded PING/INFO traffic on the next checkout; there is no per-connection
background driver, heartbeat task or reconnect worker. A server that closes an
idle connection can therefore cause the next call to fail before publication;
a later caller can establish another connection within the pool's backoff limits.
Provider epoch replacement closes future old-plan admission and the pool retires
old idle resources. Dormant deployments create no connections, requests or Stores.

`NatsSnapshot` exposes configuration epoch, mapping count and bounded numeric
activity/connection/acknowledgement/uncertainty counters. Audit contains the
existing activation/provider context, typed request digest and provider outcome;
it omits credentials, raw events, idempotency keys and broker diagnostic text.

## Composition and verification

Trusted Rust composition installs `NatsPublisher::install(pools, logical_id,
epoch, expected_epoch, config, credentials)`, compiles explicit provider bindings,
and calls `ActivationCapabilityRuntime::install_events`. The WIT contract and
current host ABI are unchanged. Ordinary standalone startup does not install this
adapter implicitly: configuration/management remains #226, guest bindings #221
and inbound durable consumer triggers #218.

```sh
cargo test --locked -p latent-nats --lib
cargo test --locked -p latent-wasmtime --test nats_events --all-features
python3 tools/run_nats_event_tests.py
```

The owned runner starts a pinned TLS broker with 256 MiB process memory, one CPU,
64 PIDs and bounded in-memory streams, then removes its server and temporary TLS
files. CI reuses the built Cargo test harness. Actual guests cover receipts,
permission errors, duplicate-window expiry, credential rotation, TLS identity,
request budgets, revocation, cancellation, outage/recovery and shared connection
reuse. A bounded TLS fault proxy withholds acknowledgements from the real broker
and verifies retained messages without automatic replay. Local regressions cover
malformed/oversized/foreign replies, control floods, original deadlines, rejected
inputs, queue cancellation and ownership after dropping a pending publication.
No load benchmark is part of this ticket.
