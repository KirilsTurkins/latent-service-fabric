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

On 1 October 2026, pinned Rust 1.97.1 on Linux passed all 301 selected library
cases: core 104, state 114, effects 75 and NATS 8. No cases were ignored or
filtered. Strict all-target, all-feature core/state/effects/NATS Clippy passed;
the focused capacity-source change also passed strict effects Clippy and six
actual protected-role admission schedules. All 48 CI contract regression cases
passed on Linux, including actual symlink rejection. UTF-8 CI coverage retained
all 88 historical obligations and observed 221 current run blocks with 132
reviewed delegated owners.

The maintained provider CI lane selects `deferred_events` through
`tools/run_nats_deferred_tests.py`. Its seven registered native schedules all
passed against the actual controlled broker in 5.33 seconds, with zero ignored
or filtered cases. Each schedule uses the protected shared store, native
captured-intent atomic writer, fixed dispatcher, protected credential references
and the original installed provider pools. An acknowledgement fault proxy
forwards to the real broker before dropping, holding or replacing replies;
independent operator inspection checks actual stored bytes and effect-derived
headers. Every owned broker, bounded storage directory and TLS file was removed.

The seven schedules cover committed state/result/payload/receipt agreement,
declared rejection and positive technical abort without outgoing effects,
presend restart with advanced physical epoch, lost acknowledgement followed by
equal-ID recovery with one broker message, expiry/revocation/stream recreation,
malformed and oversized replies, and live publication across the original
shutdown cutoff. They preserve the existing immediate and trigger campaigns
and their required CI owners. The earlier selected ownership, runner and
inventory regressions passed all 58 Python cases.

The measured identities are:

| Input | Exact identity |
| --- | --- |
| Rust qualification image | `sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97` |
| Rust toolchain | `1.97.1-x86_64-unknown-linux-gnu` |
| Broker image | `nats@sha256:065e8355c20a5575b3c77224be1855e8103fd148b68fba05130b9b8ddfa40ccc` |
| Observed broker software | NATS `2.14.6` |
| Native source base | `863b3dfd8eee573aac7874ff40c1871f071cd050` |
| `support.rs` fixture blob | `a4b73e7f80d264ef9e27c947a0a9a54fff9a7a8d` |
| `campaign.rs` fixture blob | `38df1a6af23f56e0c5393c8b3a950cf91c071cd1` |
| `proxy.rs` fixture blob | `b2baf2c21d156fadb2a11da35cd74e50e8eaec5a` |
| Native harness SHA-256 | `4460495f3504db1cdc33f0c939e72e1e70b56ef2b3f4c27a2ec92fa876665298` |

The fixture stream has file storage, one replica, 64 messages/1 MiB, discard-new,
a 30-second duplicate window, and delete/purge denied. The runner owns one
256 MiB, one-CPU broker with 64 process slots, bounded storage/logs, TLS and
explicit credentials. Its immutable container identity and random ownership
label gate cleanup. No external account or ambient credential is used.

A first success fixture used its pre-Pending admission snapshot for completion;
the real OCC engine correctly rejected the newly published command row. The
fixture now opens its coherent completion view after Pending publication.
Earlier host disk/Docker failures, that rejected fixture attempt, and one
historical immediate-campaign build that exceeded its finite fixture lifetime
remain unsuccessful evidence. They do not replace required immediate/trigger
CI execution or establish a product regression.

This native campaign executes trusted fixture source labels directly through
the captured-intent writer. Actual verified guest component identities and
ordinary standalone node delivery, rejection and recovery qualification remain
required before issue #392 can close. The shared provider factory is implemented;
the node composition and authenticated management/reconciliation paths must also
be exercised through their actual owners.
