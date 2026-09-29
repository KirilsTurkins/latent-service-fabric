# Candidate bounded stream profile v1 (uninstalled)

This is a comparison artifact, **not approved production behavior**. The exact
candidate WIT is `latent-research:outbound-streams/client@0.1.0` in
[streams.wit](streams.wit); the candidate grant profile is `bounded-streams-v1` in
[grant.schema.json](grant.schema.json). A later approval must select production
package/ABI identities, parse and generate bindings, and qualify actual components.
No production import recognition, linker, policy schema or SDK is changed here.

## Scope and states

Only outbound TCP, optionally implicit host-terminated TLS established before
returning the connection. There is no listener, bind API, UDP, raw packet access,
proxy, DNS override, local port selection, arbitrary socket option, file descriptor,
process-wide socket namespace, or hidden resident worker. No STARTTLS, protocol
TLS upgrade, TLS 0-RTT, session resumption or cross-activation connection reuse.

Internal connect states are `reserved -> resolving -> connecting -> tls-handshake
(if configured) -> open`; failure/cancel moves to `cleaning -> retired` without
returning a usable resource. Admission queues are disabled in v1. The future owns
all charges even before a guest connection handle exists. Cancellation before
connect yields no network operation; cancellation after connect starts cannot
retroactively mean the peer was not contacted.

A live `connection` is `open`, `read-eof`, `stopping`, `closed`, or `failed`.
`read` accepts a maximum of 1..16,384 bytes and returns an affine chunk or verified
transport EOF. In `read-eof`, further reads return None, but writes may continue
until shutdown/deadline. One pending read and one pending write may coexist; a
second same-direction operation fails `invalid-state`. Each operation retains
its real owner across suspension. Closing races invalidate the table generation,
prevent stale restoration and stop both directions.

`write` accepts a nonempty <=16 KiB slice and may return a successful short prefix;
its caller owns the remainder. A successful count means local transport acceptance,
not peer application acknowledgement. An error returns a known accepted prefix
for that call plus a conservative `may-have-applied` bit latched across the entire
connection. Never infer no effect from a zero count after attempting a syscall.
After transport error, the failure is sticky: no further reads/writes are issued.

`chunk-bytes` materializes at most once, with an independently reserved canonical
copy; subsequent use returns `invalid-state`. Chunk Drop zeroizes its owned storage
and releases only its own reservation. Closing the connection does not refund
retained chunk memory or an unfinished lowering operation.

`shutdown(both)` locally aborts both directions; a live repeated call is idempotent.
`send` and `receive` return `unsupported` without performing half-close in v1.
In particular, TLS close-notify is not equated with TCP SHUT_WR or peer rollback.
`close` consumes the resource and retires actual socket ownership. Implicit Drop
invalidates the table entry, requests cancellation and initiates the same bounded
local retirement; it does not perform peer I/O or enqueue unowned cleanup.
An invalid canonical handle traps or yields the adapter's exact invalid-state
result, never a fabricated connection/observation. `inspect` is a local snapshot
for a valid resource, not an authorization or cleanup proof.

Errors have a bounded enum, accepted-prefix count and uncertainty bit, not a raw
provider string. `invalid-input`, `denied`, `revoked`, `exhausted`, `dns-failed`,
`tls-failed`, `connect-failed`, `timeout`, `cancelled`, `unexpected-eof`, `io-failed`,
`unsupported` and `invalid-state` stay distinguishable. For a raw stream, ordinary
EOF is observable without knowing whether the application's frame was complete;
the library must convert premature protocol EOF to its own failure. No error or
EOF manufactures a database rollback, mail delivery or durable effect receipt.

## Authority, credentials and DNS/TLS

The host compiles exact actual import, tenant/principal, activation publication,
deployment restrictions, destination alias **and port**, provider binding, immutable
configuration digest and epoch. Bind and each accepted connect/read/write intersect
all of these with current policy and original descendant budgets. Parent service
invocation cannot delegate more destination, concurrency, byte or deadline
allowance than it owns. Package attribution is diagnostic, not a new principal.
The schema's integer epoch is explicitly bounded to the exact JSON-safe range;
any future u64 representation change needs a new schema version.

A guest supplies a configured alias and allowed port, not a hostname or certificate
policy. An HTTP path/method grant authorizes only the HTTP request it describes;
no `CONNECT`, raw upgrade or byte-stream authority follows from it. A gateway called
through HTTP authenticates the caller and independently authorizes its typed
operation and remote destination. Mapping an arbitrary SQL string or target URL
would erase the intended benefit of that gateway and is not the preferred design.

Reuse the production HTTP address-policy/resolver components rather than a parallel
resolver. Resolve only with an explicit bounded configured recursive resolver or
static answer list. Bound each DNS packet to a proposed 4 KiB, records to 32 and aliases to 8;
retain the existing HTTP ceilings of <=8 addresses and maximum TTL 300 seconds. Normalize
hostname and IPv4-mapped IPv6 before comparison; reject userinfo, wildcard/zero
ports and ambiguous forms. The JSON candidate performs **structural checks only**;
these semantic checks, unique aliases, valid hostnames/CIDRs and cross-limit
relationships are mandatory at a future trusted configuration compiler.

Each answer, including mixed A/AAAA and CNAME resolution results, must satisfy
both permitted networks and explicit exact special-address exceptions. Private,
loopback, link-local, metadata, multicast, unspecified, documentation, translation
and transition ranges are not authorized merely by a broad CIDR. Reject the entire
mixed answer on any denial. Before the actual connect, recheck current grants,
epoch and resolution expiry; pin one approved literal address and verify the
connected peer matches. One attempt chooses one allowed address, with no automatic
address fallback. Reconnect is a new charged, authorized attempt. An established
connection does not follow DNS changes; an expired address/policy validity stops
new operations and closes the old owner. No pool exists to evade revalidation.

Host TLS validates the original configured server name, certificate validity,
chain and selected trust roots; minimum TLS 1.2, maximum the supported TLS 1.3
profile, no insecure override or cleartext fallback. Root contents and TLS policy
are immutable configuration inputs. Certificate revocation/expiry policy must be
explicit: this candidate proposes no unbounded online OCSP/AIA fetch. A future
operator profile must bound root/certificate validity and any locally provisioned
revocation material; it must not advertise online revocation checking without
implementing it. Root/credential revocation closes future admission, with emergency
stop requesting cancellation of active streams under their retained owners.

TLS authenticates transport, not protocol permissions. In this candidate v1 there
are **no injected protocol credentials or mTLS client keys**. Host-held AUTH/login
credentials cannot be inserted into arbitrary unknown protocol bytes safely;
a protocol-aware provider/gateway is required for that. A guest explicitly granted
secret bytes would possess those bytes under a separate capability and trust
policy; TCP permission alone grants no secret read. Typed providers bind opaque
secret references to tenant/provider/destination, suppress protocol trace logs,
zeroize their owned copies and rotate epochs without session reuse. This POC
contains no credentials and does not qualify those mechanisms.

Required production audit reserves finite capacity before dispatch and records
identity, approved destination alias/port, provider digest/epoch, operation,
accepted bytes, evidence and uncertainty without payloads, credentials or raw
peer messages. The candidate must use the existing dispatch barrier, not the
prototype's in-memory audit list. Bind/new operations fail closed if required
audit capacity is unavailable. Revocation before the guarded start prevents I/O;
already accepted work may finish under original ownership, following the broker's
existing semantics. Emergency cancellation cannot prove remote rollback.

## Resource and retirement contract

Proposed hard ceilings below are **design limits, not measured production limits**.
Actual admission is the minimum of these, the original broker session/call caps,
parent/descendant ledgers, global I/O limits and tenant/provider policy.

| Dimension | Candidate ceiling |
| --- | --- |
| Active connections | 2 activation, 16 tenant, 32 provider, 64 process-wide |
| Cumulative connect attempts | 32 activation, nonrefundable once dispatched |
| Queued calls / shared idle connections | 0 / 0 |
| Chunk / live payload capacity | 16 KiB / 64 KiB per connection including lowering copies |
| Cumulative transfer | 1 MiB each direction per connection; 2 MiB combined per activation |
| Table/connection metadata | prepay 1 KiB table row + 16 KiB protocol/owner allowance |
| Requested kernel buffers | 16 KiB send, 32 KiB receive, prepay 96 KiB logical allowance |
| TLS allowance | prepay separate 64 KiB plus bounded root material; implementation must prove or revise |
| Retained chunks | maximum 4 per connection, additionally limited by shared buffer/result caps |
| Idle / absolute lifetime | 2 seconds / 10 seconds, narrowed by original activation/parent deadline |
| Cancellation observation / cleanup grace | existing I/O probe interval and node grace; no OS latency guarantee |

Reserve handles, metadata, staging, TLS objects and socket capacity before their
allocation. Count initialized vector capacity, pending write chunks, raw/decoded
TLS storage and canonical copies separately. Kernel buffer options may round or
double; measure actual supported OS behavior during qualification and reject or
revise the profile if the declared bound cannot be maintained. Logical accounting
is not exact allocator or RSS accounting. A 64 KiB TLS allowance is **not** proven
by the Go experiment, which is one reason production remains deferred.

Backpressure is one owned pending read/write per direction, no unbounded queue or
prefetch. Once retained chunks exhaust allowance, reject or suspend before another
transport read while retaining the operation deadline. Waiting does not release
the execution cell. Dropping/reopening resources refunds live memory only after
physical destruction; it cannot reset cumulative connect/byte budgets.

One monotonic absolute deadline covers admission, DNS, connect, handshake, all
reads/writes and delivery. Only positive application progress renews idle time;
notifications, poll loops, empty calls and retries do not extend it. Absolute
expiry is terminal even during steady trickle traffic. Stop wakes pending I/O,
closes admission and sockets, and joins any actual owner/callback before release.
An OS stall beyond the existing grace leaves the cell/owner quarantined rather
than falsely reusable. No timer, socket task, TLS state, authenticated session,
chunk or guest heap can become a dormant per-application allocation.

The implementation path must reuse `IoRuntime::admit_until`, `IoReady::start`,
`IoCall::wait_for`, `CapabilityStreamBudget`/`IoTransfer`, Store table reservations,
provider registry epochs and the existing after-Store cleanup observer. A fresh
parallel executor, universal proxy or per-application pool is not acceptable.
The candidate requires new capability recognition and host binding work; none of
that is delivered by changing this research WIT or schema.

## Explicit prerequisites to reconsider production

Use actual #679/#680 and language findings to select a valuable non-HTTP path.
Then qualify this contract through the real broker, original/descendant budgets,
shared owners, Wasmtime resources and at least one real compatible guest/library,
including forced cancellation during dispatch/write/read/lowering. Parse WIT,
validate semantic policy, prove no-connect denials and DNS rebinding resistance,
measure allocator/kernel/TLS costs, test revoked epochs and held chunks, and
complete operator/audit/trust rotation procedures. Record any revised ceilings and
review the capability/ABI version. These are future production gates, **not hidden
dependencies of HTTP adapters or ordinary third-party dependency support**.
