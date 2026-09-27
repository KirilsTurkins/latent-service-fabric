# Bounded NATS JetStream triggers

`latent_nats::triggers::NatsTriggers` implements the operator-installed
`nats-jetstream-pull-v1` profile.
It delivers external events through the existing publication catalog, admission
controller, scheduler and fresh activation stores. It uses the same confined TLS
transport and rotating opaque credentials as the [publisher](nats-events.md).
It adds no guest import and no transactional outbox.

## Authority and binding

Each `TriggerBinding` fixes an ID, tenant, trusted principal subject, service,
contract, function, optional route, stream, durable consumer, exact filter subject
and reduced root budget. The host derives a `Trigger` principal, a fresh root
activation ID and trace. Event bytes and headers cannot select authority, lineage,
route, budget or deadline. Payloads must encode the selected function's argument
array using `application/vnd.latent.wit-values.v1+json`. Put application-level
deduplication keys in that payload when required.

Bindings have unique IDs and stream/consumer pairs. Different tenants cannot use
the same physical filter subject in one configuration. Up to eight tenant clients
share a configuration; every tenant needs its own `NatsCredential` bound to that
tenant, provider ID and exact TLS destination. Broker credentials should permit
only the configured consumer-info, pull and acknowledgement subjects and private
reply inboxes. Provision consumers separately with operator credentials.
Production trigger code cannot create streams or consumers.

TLS uses one approved IPv4 socket and independently verified server name.
Non-public addresses require exact opt-in. The profile requires handshake-first
TLS and supports no DNS discovery, reconnect loop, plaintext, proxy or automatic
redirect. The pinned conformance broker is NATS 2.14.6; its image and transport
details are recorded in the [publisher profile](nats-events.md).

## Finite pull and activation ownership

Installation retains metadata only. The embedding runs one caller-owned
`run(&manager, stop_receiver)` future, or drives `step` explicitly. One loop and
timer rotate tenants and then each tenant's bindings. Each step handles at most
one message and one activation. There is no task, socket, retry timer, subscription
or long-running activation allocated per dormant service.

Before contacting the broker, `LocalActivationManager::reserve_inbound` pins the
route and reserves admission and the maximum input allocation. It creates no guest
store or execution cell. An unavailable quota causes no pull. The provider then
reserves a shared ingress request, response/framing memory and connection capacity.
The request permits exactly three protocol operations: inspect consumer, pull one
message, and acknowledge its terminal outcome. Socket/parser ownership remains
charged through cancellation and cleanup. Empty polls drop their node reservation;
they can create bounded journal history but do not prepare or invoke a guest.

Publication eligibility is checked before networking and again before pulling.
Credential currentness is checked before the pull and acknowledgement. Accepted
input keeps its original admission, route generation and deadline; future pulls
resolve current routes. The backend retains its final guarded start check, so a
cached component does not authorize a revoked publication.

| Profile setting | Supported bound |
| --- | --- |
| Trigger bindings | 1–256; each name bounded, no wildcard filter |
| Tenant clients | 1–8; lazily created and shared across their bindings |
| Payload | 1–32,768 bytes |
| Headers / protocol lines | At most 8 KiB each; finite control-frame processing |
| Delivery operation timeout | 100–10,000 ms, one original deadline |
| Root wall-time budget | Positive, at most the operation timeout |
| Poll interval | 10–1,000 ms; one timer for the owner |
| Broker delivery count | 1–16 |
| Broker acknowledgement wait | At least operation timeout + 1,000 ms, at most 60,000 ms |
| Negative-ack delay | 100–10,000 ms |
| Retained public configuration encoding | At most 512 KiB |

Shared [provider pool](provider-pools.md) limits additionally bound all providers'
requests, metadata, clients and connections, including tenant/provider ceilings,
idle age and dial backoff. Installation charges 64 KiB plus 2 KiB per binding and
six times retained root-certificate bytes. Each ingress request charges 64 KiB
plus twice the payload ceiling; physical TLS connections have a separate 256 KiB
reservation. These are accounting bounds, not whole-process RSS measurements.

## Broker profile and terminal outcomes

The consumer-info reply must identify the exact stream, named durable consumer
and filter. Required settings are explicit acknowledgement, instant replay,
deliver-all, `max_waiting = max_ack_pending = max_batch = 1`, `max_expires =
100000000` ns and `max_bytes = payload_ceiling + 9216`. `ack_wait` and `max_deliver`
must match the operator configuration. Push delivery, headers-only delivery,
flow control, multiple filters and consumer backoff arrays are rejected.

Each pull requests batch one with no-wait and a 100 ms expiry. Known empty,
expired or capacity-limited replies stop that pull. Oversized, malformed or foreign
frames close the connection and are observable errors; they never trigger an
unbounded drain or local replay queue. Operators must ensure stream messages fit
the configured payload ceiling. Messages the broker cannot deliver within its
byte limit require operator correction.

Acknowledgement subjects are parsed using a closed grammar and checked against
the configured stream/consumer and positive sequence/count fields. Classic and
no-domain v2 subjects are supported; arbitrary reply subjects are rejected.

| Activation outcome | Broker action |
| --- | --- |
| Success | `+ACK` |
| Declared application failure | `+TERM` |
| Invalid arguments, incompatible contract, authentication or permission rejection after delivery | `+TERM` |
| Timeout, cancellation or other platform failure | Delayed `-NAK` while attempts remain |
| Retryable failure at the configured last delivery | `+TERM`, reported as exhausted |
| Operator shutdown with pending work | Close/reclaim locally, leave delivery unacknowledged |

ACK, NAK and TERM all require a broker acknowledgement. A possibly written command
without its verified receipt is **uncertain**. This applies both when the broker
committed the command and when the command never reached it. There is no automatic
acknowledgement replay. Unacknowledged messages can redeliver and execute the guest
again. Successful acknowledgement is unrelated to an LSF transaction or downstream
external-effect durability. See the [NATS pull-consumer contract](https://docs.nats.io/learn/jetstream/pull-consumers)
and [acknowledgement protocol](https://github.com/nats-io/nats-architecture-and-design/blob/main/adr/ADR-13.md).

## Configuration, recovery and operations

Trusted Rust composition calls `NatsTriggers::install(pools, logical_id, epoch,
expected_epoch, config, credentials)` and retains its `TriggerMonitor`. Persist
only validated `TriggerConfig::to_json()` bytes and the separately protected
credential configuration. Restore with `TriggerConfig::from_json`; local offsets
or delivery receipts are not persisted. The broker owns durable consumer position.
Configuration replacement uses the provider registry's checked epoch transition.

`TriggerMonitor::snapshot` reports bounded aggregate counts. `last_step()` retains
one fixed-size terminal/error report with configuration epoch, binding index,
stream sequence, delivery count, pinned route generation and acknowledgement state.
It contains no payload, broker diagnostic string or secret. An empty poll does not
erase it. A sequence of failures requires external observation; this slot is not
a durable event log. Consumer delivery exhaustion remains observable in the broker
even when a node cannot receive the final attempt.

Signal the watch channel and await `run` to finish cleanup. Explicit `step` users
call `close_idle()` when stopping; shared pool shutdown owns final reclamation.
Dropping an activation waiter is not a substitute for driving backend cleanup.
The standalone node has no NATS trigger installation field. Supply this
configuration, protected credentials and the owned run future through the Rust
embedding; declaring a trigger alone cannot start an external broker connection.

```sh
cargo test --locked -p latent-nats --lib
cargo test --locked -p latent-node --test activation_lifecycle
python3 tools/run_nats_event_tests.py --suite nats_triggers
```

The owned runner uses one pinned TLS broker with 256 MiB memory, one CPU, finite
streams and bounded logs, and removes its files and container. CI reuses the built
test harness. Actual broker/node/Wasm tests cover 256 idle bindings, overload,
two-tenant fairness, connection reuse, route replacement, scoped revocation,
declared failure, invalid payloads, finite poison retries, both lost-ack cases,
restart redelivery, and pending/executing shutdown cleanup. No large benchmark
campaign or retained broker data is required.
