# Bounded standard outbound stream profile v1

This is the frozen proposal owned by [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md)
and [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737).
Production installation remains disabled pending architecture/security review,
provider #738, operator #739 and conformance #740. The current shipped HTTP
profiles are unchanged. The candidate [WIT](../../research/standard-outbound/streams.wit)
is comparison input, not an installed capability.

## ABI, operations and states

Identity: `latent:network/streams@0.1.0`; feature/profile:
`lsf-outbound-streams-v1`; WIT canonical async operations and affine resources.
`connection` and `chunk` are Store-local resources, not native descriptors.
There is no process-wide descriptor namespace.

| Operation | Contract |
| --- | --- |
| `connect(host, port, transport, timeout)` | Normalized exact configured host/port/transport; one selected validated address and one attempt. Timeout can narrow the root/parent deadline. No fallback address, proxy or retry. |
| `read(connection, max, timeout)` | 1..16,384 bytes; a bounded owned chunk, ordinary transport EOF (`none`) or a closed error. Partial frames remain the guest parser's responsibility. |
| `write(connection, bytes, timeout)` | Nonempty 1..16,384 bytes; short accepted prefix is valid. No implicit write-all retry. Error preserves an accepted-prefix lower bound and connection-wide possible-write uncertainty. |
| `ready(connection, interest, timeout)` | Await readable, writable or either; readiness is a hint and subsequent I/O may still would-block. EOF is readable. Never reads, writes, reconnects or refreshes idle time. |
| `chunk-bytes(chunk)` | Materialize once; resident data and canonical copy remain prepaid until Drop. |
| `inspect(connection)` | Local bounded state/byte/uncertainty observation; not authorization or remote outcome. |
| `shutdown(connection, direction)` | TCP send half-close sends FIN after accepted local writes; TCP receive half-close is unsupported. Host TLS send/receive half-close is unsupported. `both` aborts both transports locally. No remote rollback/acknowledgement. |
| `close(connection)` | Consume the logical resource and destroy actual local socket ownership before refund. Outstanding chunks and pending callbacks retain their own charges. |

Connect transitions `reserved -> resolving -> connecting -> tls-handshake
(host-tls only) -> open`; any error goes `cleaning -> retired` without returning
a usable resource. A connection is `open`, `read-eof`, `write-shut`,
`read-eof-write-shut`, `stopping`, `closed` or `failed`. Transport failures and
root cancellation are sticky. Ordinary EOF permits writes; send half-close
permits reads. One pending operation per direction and one readiness waiter per
connection are allowed; another same-direction operation returns `invalid-state`.
Closing invalidates the generation, prevents stale restoration and wakes waits.
Close/drop performs no peer protocol commands and never starts detached cleanup.

Unsupported operations fail before dispatch: listen/accept/bind/local port
selection, UDP, raw packets, arbitrary socket options, receive half-close,
host TLS upgrade/STARTTLS, host TLS custom pinning/client keys, descriptor export,
cross-activation reuse, ambient DNS/proxy, TLS 0-RTT/session resumption and transport
fallback. Supported guest TLS remains owned by the named language runtime; its
available crypto/trust/pinning/client-key APIs require separate measured evidence.

## Error mapping

The WIT error record carries a closed code, accepted-prefix bytes for that write
call and a sticky `may-have-applied` bit. Codes are `invalid-input`,
`invalid-state`, `unsupported`, `denied`, `revoked`, `exhausted`, `dns-failed`,
`tls-failed`, `connect-failed`, `timeout`, `cancelled`, `io-failed` and `uncertain`.
An API timeout is distinct from root cancellation. A failed operation following
an attempted write conservatively retains uncertainty even when its prefix is zero.

| Language boundary | Required mapping owned by its standard-runtime port |
| --- | --- |
| Rust `std::net`/selected reactor | `io::ErrorKind` permission, unsupported, invalid-input, would-block, timed-out, connection/reset/EOF distinctions; typed uncertainty retained in error context. |
| C POSIX/libc | `EACCES`, `ENOTSUP`, `EINVAL`, `EAGAIN`, `ETIMEDOUT`, `ECANCELED`, transport errno and actual short counts; uncertainty exposed in bounded diagnostic context. |
| Go `net.Conn` | `*net.OpError`, timeout interface, `context` cancellation and `io.EOF`; retain `n > 0` with errors rather than discarding progress. |
| Java `Socket` | Catchable socket/security/timeout/unsupported exceptions; `InputStream.read == -1` at EOF, real partial counts. |
| TypeScript selected Node API slice | Pending callback/Promise and bounded native-style error codes; zero read does not fake success/EOF, preserve stream error/close ordering. |
| .NET `Socket`/`NetworkStream` | `SocketException`, cancellation/timeout distinctions, partial counts, EOF and actual incomplete Task completion. |

Each port must publish its exact source API/error implementation. This mapping
plan cannot qualify language behavior by itself. Unknown dynamic paths remain
unknown in #679 diagnostics; no package catalogue controls runtime availability.

## TLS and protected inputs

`tcp` exposes opaque authorized bytes. Qualified guest TLS preserves standard
library chain/hostname validation, pinning, direct TLS, explicitly granted client
keys and STARTTLS, with guest-visible secrets and charged entropy/TLS/parser/native
memory. TCP permission does not grant secret reads or attest encryption.

`host-tls` is separately explicit and immutable: TLS 1.2/1.3, original configured
server name, selected DER/public trust roots, validity/hostname checking, no
insecure override, cleartext fallback, online AIA/OCSP, custom guest verification,
client key injection, resumption or 0-RTT. Root/credential input rotation changes
configuration epoch and never migrates authenticated sessions. Protected files
are resolved by existing protected owners; no raw path or secret belongs in
arguments, lockfiles, images, catalogue entries, logs or public receipts.
Opaque protocol credentials cannot be inserted by the shared provider.

## Authority, DNS and currentness

Use a distinct `stream` resource: exact canonical host, nonzero port and `tcp`
or `host-tls`. No wildcard endpoint/port/transport, URL/userinfo, ambiguous address,
implicit HTTP CONNECT or grant conversion. Normalize at the language boundary,
then require the trusted configured canonical representation. IPv4-mapped IPv6
uses `latent-network::canonical`. Source requirements suggest review; publication,
tenant and provider grants must be issued independently. Strict transactional
execution denies these immediate effects.

Before DNS and again before connect/read/write, intersect sealed session,
publication, tenant, provider digest/epoch and original budget/currentness.
Reuse `latent-network::AddressPolicy` and its resolver: <=8 answers, maximum TTL
300 seconds, <=5 CNAME traversal entries, bounded wire decoding. No platform
`getaddrinfo`, environment proxy or guest-selected recursive resolver. Reject an
entire answer containing a denied address. Permitted networks alone never enable
special/private/loopback/link-local/metadata/documentation/transition addresses;
those require an exact explicit exception and cannot include unspecified/multicast.
Connect one approved literal address; verify the actual peer address/port. No
address fallback. An established stream never follows DNS changes; bounded
resolution expiry closes future operations and retires its owner.

Audit uses the existing required dispatch barrier and a finite reserved record.
Record tenant/publication/session/provider/destination identities, operation,
byte counts, evidence/uncertainty and rejection class. Never inspect/store payload,
protocol replies, keys or invented SQL/mail/HTTP attribution. No capacity means
no new dispatch. Credential/revocation/rotation fences deny new work while
already accepted physical work retains its original charge until destruction.

## Caps, suspension and physical retirement

All limits intersect the original activation/parent ledger and node IoRuntime.
One logical thread cannot mint another budget. No provider admission queue or
idle authenticated connection pool exists for this profile.

| Dimension | Hard maximum; configured policy may narrow |
| --- | --- |
| Live connections | 2 activation, 16 tenant, 32 provider, 64 process |
| Cumulative connect attempts | 32 activation; dispatched attempts never refund |
| Read/write windows | 16 KiB each; 4 outstanding chunks; <=64 KiB connection live payload including lowering copies |
| Cumulative transfer | 1 MiB each direction/connection, 2 MiB combined/activation |
| Metadata | Prepay 1 KiB table row, 16 KiB owner/operation state |
| Socket buffers | Request send 16 KiB/receive 32 KiB; reserve 96 KiB logical kernel allowance, inspect actual OS sizes and reject overflow |
| Host TLS | Separate 256 KiB logical allowance plus bounded configured trust roots; physical peak qualification remains required |
| Lifetime | Idle <=2 seconds, absolute <=10 seconds, narrowed by parent/root deadline |
| Waiters | One read, one write and one readiness waiter; bounded #736 wait/timer/frame admission |
| Cleanup | Existing node/Store cleanup grace and quarantine; no refund on request/ack/handle drop alone |

Reserve handles, metadata, input/native/TLS/kernel allowances before allocation
or contact. `IoTransfer` owns resident chunks and copy reservations independently
of cumulative bytes. Backpressure rejects/parks before reading more transport
data. Guest TLS/parser storage has a separate allocator/guest-memory bound;
transport bytes are insufficient to bound a hostile protocol parser. Logical
reservations do not measure RSS/allocator/kernel peak usage.

#736 readiness records park only the calling logical thread with sealed Store
generation; siblings/nested calls may progress. No mutable Store borrow spans
external I/O. Only positive read/write progress renews idle time; polling, DNS,
notifications or trickle beyond the absolute deadline cannot extend activation.
Cancellation wakes owners but cannot prove remote rollback. Socket, TLS, pending
I/O, buffer, callback and execution-cell charges survive until physical retirement.
An unretired owner after grace quarantines capacity; watchdog expiry is failure.
A fresh activation/tenant inherits no authenticated connection or guest state.

## Exact source/WASI comparison and finite qualification matrix

[`wasi:sockets/tcp@0.2.0`](https://github.com/WebAssembly/wasi-sockets/blob/v0.2.0/wit/tcp.wit)
has start/finish-connect, network/address arguments, an input/output stream pair,
pollables, listen/bind/accept/options and three shutdown directions. LSF's
canonical async connect, charged affine chunks and sealed endpoint policy require
real adaptation. Preserve one owned attempt across start/finish/poll; readiness
does not guarantee completion. Deny unsupported members before contact. The
[name-lookup contract](https://github.com/WebAssembly/wasi-sockets/blob/v0.2.0/wit/ip-name-lookup.wit)
also admits IDNA and separate resolve streams; the LSF port must map normalized
names and bounded address lifetimes, not expose ambient network authority.

The source/ABI probe emits the candidate types and a real component whose unknown
WASI socket import must be denied. Its negative result establishes current
recognition only, not provider execution or standard-library compatibility.

| Port owner | Finite standard API + unchanged non-HTTP workload | Required compiler/runtime evidence |
| --- | --- | --- |
| Rust #743 | `std::net::TcpStream`; lettre 0.11.23 default SMTP transport with explicitly captured feature selection | Rust 1.97.1 wasm sysroot/reactor; guest rustls TLS/pinning/entropy and allocator |
| C #744 | `socket/connect/read/write/poll`; libcurl ordinary SMTP factory and write callback for message data only | Pinned WASI SDK/libc port; exact libcurl and TLS closure selected by capture, no custom socket callback |
| Go #742 | `net.Dial/net.Conn`; Go 1.27.1 `smtp.Dial`, `crypto/tls` STARTTLS | Exact patched compiler/sysroot; goroutine/wait/deadline/TLS ownership, not the historical native POC |
| Java #741 | `Socket/InputStream/OutputStream`; Angus normal SMTP transport including scheduled write timeout | TeaVM 0.15.0 classlib/socket/crypto/runtime patch; service-loader/resource graph captured |
| TypeScript #745 | Finite Node `net.Socket`/`tls`/timers slice; Nodemailer normal `createTransport` | Actual selected engine/runtime/bundler with bounded callback/stream/TLS semantics, not browser fetch alone |
| .NET #746 | `Socket/NetworkStream/SslStream`; MailKit ordinary host/port `Connect` | Captured Componentize.NET/NativeAOT BCL/native/TLS/Task closure; no injected Stream |

Versioned library rows select evidence, never package authority. Each receipt
freezes every library/transitive artifact/feature, compiler, runtime port/preimage,
patch, WIT/ABI/engine, configuration digest, component hash and tested source.
Unselected third-party version cells remain pending until the controlled resolver
captures their actual closure; this profile does not invent a successful graph.
Every language also runs an outside-checkout catalogue-absent/renamed private
dependency and a hardwired standard socket client with a transitive worker/timer.

Shared deep tests cover: allowed TCP/host TLS; denial with zero DNS/connect;
HTTP-only/strict-transaction denial; forged/foreign/stale/double-close handles;
special-address/mixed-answer/rebinding and trust/hostname failures; split/short
I/O, partial frames, EOF/approved half-close, backpressure, reset, peer stall and
oversized/unterminated parser input; lost mutation reply with observed attempts
versus peer mutations and no host replay; cancel request/ack/actual retirement,
late completion/Store destruction/reuse, terminal trap and node stop; every
handle/queue/timer/frame/native/TLS/kernel/byte cap; rotation/revocation/drain,
quarantine and fresh authorized cross-tenant work. Deterministic peer/owner
barriers establish transitions; timeout alone is never cleanup evidence.

#738 supplies shared provider controls/focused tests, #739 protected operation,
#740 implementation-backed receipts and measurements, #679 diagnostics and #694
the six-language aggregate. Missing operations require exact reproducers and
owner links. No all-six claim is made while any language cell is pending.
