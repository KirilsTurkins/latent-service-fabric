# Proposed companion contract for nonblocking outbound streams

Status: **proposed, owner decision required**. The accompanying
[WIT](nonblocking-v2/package.wit) is an uninstalled research contract, not an
ABI recognition, runtime capability, policy grant, implementation or qualification.
The accepted
[ADR-0061](../../adr/0061-bound-standard-outbound-streams.md), the
[v1 profile](../../docs/runtime/outbound-stream-profile.md), its exact WIT and
existing grants remain unchanged. Production remains disabled. This proposal
does not resolve the named-host association required by the ordinary C client.
[Validation instructions](README.md#nonblocking-companion-proposal) keep the two
package identities in separate parse directories and stage the exact v1 dependency.

## Trigger and identity

The selected libcurl 8.23.0 source requests `SOCK_NONBLOCK` at socket creation
on its normal path and `SOCK_CLOEXEC` in `socket_open`. The optional opensocket
callback path sets nonblocking later via the selected `fcntl` implementation.
Its `Curl_socket_check` asks for `POLLPRI`; `POLLERR`, `POLLHUP` and `POLLNVAL`
also have observable effects. Current v1 readiness exposes only readable and
writable, and its `timeout` cannot distinguish a benign observation deadline
from original connection expiry. No C port may infer a benign timeout from
`inspect`, suppress `POLLPRI`, or return `EAGAIN` while physical I/O continues.

The proposed identity is `latent:network-nonblocking/streams@0.2.0`. It uses
the exact v1 `connection`, `chunk`, `connect-request` and `stream-error` types;
only `connect-attempt` is a new resource. A host that does not explicitly
recognize and install this separate interface rejects its import. Existing v1
worlds remain unchanged, and the same broker, endpoint grants, authority
checks, budgets and v1 close/chunk/shutdown operations apply. Version selection
does not itself grant access or authorize promotion to production.

## Admission and connect state

`begin-connect` performs bounded preadmission and creates one original owned
attempt. It checks the exact normalized host, port and transport before DNS and
physical contact, preserving v1 resolver/address policy and no-fallback rule.
Before dispatch, reserve the original connection slot, native allowances,
future/operation state, audit record and required wait capacity from the
existing ledger; no separate unbounded queue or executor is introduced. An
attempt counts against the existing connection and cumulative-attempt limits.
The call may suspend for admission and audit, but does not wait for socket
connect completion before returning the admitted attempt.

The state machine is `pending -> connected | failed -> consumed`. Completion is
monotonic. `get-connect-status` reports the actual state with the original error on
failure; its own error represents a failed guarded observation, not a fabricated
connect result. Observations do not take or replace physical ownership.
`finish-connect` consumes the attempt on **every** outcome. On connected success
it transfers the very same socket/charges into a v1 connection; on failed or
premature invocation it returns the error and retains cleanup responsibility.
The C port calls it after a terminal observation and handles a changed authority
or terminal failure during the handoff. `cancel-connect` also consumes the
attempt. A successful cancellation means the physical operation and its owned
resources retired, not merely that cancellation was requested; otherwise report
failure and retain the original charges in the existing bounded quarantine.
Dropping an attempt or abandoning any suspended call must preserve the same
physical owner and charge until retirement, including when `begin-connect` was
cancelled after dispatch but before its handle reached the guest. No callback or
socket may contact a peer after its owner has been retired or restore into a
reused Store/descriptor generation.

`connect-complete` is an internal observation that an attempt is terminal; it
does not by itself mean the connection succeeded or that the socket is writable.
The adapter retrieves the guarded result, transfers or retires the attempt and
reports only actual events appropriate to that result. A failed attempt without
an established socket must still wake its observer so its actual error can be
reported. Completion processing cannot restart the caller's poll deadline.

An opt-in C adapter may map one admitted in-progress attempt to `EINPROGRESS`,
report actual completion through polling and consume the result when serving
`SO_ERROR`. It must keep pending and already-connected outcomes distinct,
preserve error consumption semantics, and fence close/cancellation. Implement
`SOCK_CLOEXEC` and the callback's `F_GETFL/F_SETFL` only with accurate local
flag/process behavior. No claim is made that the current socket-only table can
coexist with WASI file descriptors: mixed socket/stdio/file polling needs a
separately proven common namespace or safe demultiplexer.

## Immediate transfers

`try-read` accepts 1..16,384 bytes and returns an owned charged v1 chunk, EOF,
`would-block`, or the original error. `try-write` accepts a nonempty input of
at most 16,384 bytes and returns a positive actual accepted count, `would-block`,
or the original error, including its accepted-prefix lower bound and uncertainty.
The C adapter handles legal zero-length POSIX calls before invoking the WIT.

`would-block` is valid only after a real immediate attempt accepted/consumed no
bytes and left no physical I/O pending. It is not an alias for timeout,
cancelled, denied, revoked, audit failure or uncertain completion. Admission
and required audit can suspend, but the physical attempt cannot secretly keep
reading/writing after `would-block`. Prior connection-wide write uncertainty is
not cleared by `would-block`. Preserve the original input/output buffers,
transfer charges, audit reservation, pinned per-operation authority and
post-I/O currentness. A failure after bytes were consumed or accepted follows the
existing read-custody and uncertainty rules; never erase evidence to return
`EAGAIN`. Empty writes, partial writes and EOF have their normal distinct C
meanings and no hidden retry.

## Readiness and deadlines

`observe` receives 1..8 watches, with at most two distinct live connections or
attempts under the existing activation connection cap. Duplicate watches are
allowed. One prepaid readiness waiter per distinct underlying resource is shared
among its duplicates; the ordered result has one event mask per input entry.
Concurrent v1 and companion operations share the existing per-direction waiter
limits; duplicate watches and interface selection do not create extra allowances.
Only requested readable/writable/priority bits are returned, while actual
hangup/error bits and a terminal attempt's `connect-complete` may be returned
regardless of interest. `connect-complete` is never returned for an established
connection. `ready` requires exactly the input number of masks and at least one
nonempty mask; malformed output is failure, not an empty observation.
`elapsed` is a successful empty observation. A physical
socket error may be an event, with its concrete failure obtained from the
appropriate operation; authority/admission failure, revocation, cancellation,
root/idle expiry and inability to observe faithfully are errors, not `elapsed`.
Do not synthesize `priority` or suppress it for unsupported transports.

An optional timeout is 0..10,000 ms, starts when the host receives the call,
and cannot extend the original call,
activation, absolute or idle deadline. Zero requests one physical snapshot
without waiting for a socket event. `elapsed` is legal only when the observation
deadline wins strictly before the original deadlines and the same operation's
authority and lifetime remain current after required audit; expiry/revocation
wins ties. The implementation records the actual outcome before returning and
never uses `inspect` as authorization or timeout provenance. Readiness is a hint;
the following transfer may still return `would-block`. Polling does not renew
idle time. All waiters and their original owners are joined or kept charged
through cancellation, failed audit, close and Store teardown.

The C adapter handles negative and invalid descriptors locally, including
`POLLNVAL`, and maps duplicate entries and requested masks without discarding
other entries' actual events. Descriptor-free waits and non-socket descriptors
remain outside this interface. Per-operation errno and `SO_ERROR` mapping must
not claim a transport event when guarded admission or audit failed.

## Authority boundary and unresolved DNS association

The existing exact canonical host/port/transport grant remains necessary before
DNS and contact; an IP match, inferred protocol, HTTP grant, ambient resolver or
guest-selected recursive server never creates authority. `begin-connect` accepts
the existing v1 request when a caller already has that hostname, but this does
not solve ordinary C `gethostbyname(name)`: it has no port, and a later copied
`sockaddr` has neither hostname provenance nor an opaque resolution handle.
This design intentionally defines no synthetic address, global name cache or
IP-to-host grant conversion. A separately reviewed design must preserve the
exact association across copies, concurrent clients, colliding DNS answers,
literal-IP calls, tenants and policy rotation, or fail closed. The current
literal-IP profile remains limited and cannot satisfy named-host libcurl.

## Decision and qualification gates

Owner review must explicitly accept or reject the new identity, attempt and
waiter lifecycle, event surface, timeout precedence, per-operation audit fences
and unchanged resource/authority bounds. `priority` observation extends the
separate companion's event surface, not the frozen v1 interface. It does not
authorize `MSG_OOB` data, raw sockets, UDP, listener/bind, ambient DNS, replay or
a new TLS placement. The proposal does not convert v1 grants or authorize any
of those unsupported operations.

Only a backend with proven physical semantics may implement each operation.
Plain host TCP is a candidate for an initial development-only implementation;
host TLS and protected/q35 remain unavailable for the new behavior until their
own ownership, observation and retirement controls pass. Existing configured
limits remain in force: at most two activation connections, 32 cumulative
attempts, 16 KiB windows, four live chunks, 2 MiB aggregate activation
transfer, original per-direction waiters, 2-second idle and 10-second absolute
maximums, narrowed by parent policy and budgets.

Required qualification includes actual TCP empty-poll versus idle/root expiry,
revocation during audit, `POLLPRI`/hangup/error and duplicate/multiple watches;
backpressure without late I/O after `would-block`; partial accepted writes;
pending connect cancellation, stale Store/descriptor reuse and physical
retirement; unchanged v1 refusal and grant controls; and real signed ordinary
libcurl easy/multi execution with its selected TLS closure. The named-host
association, mixed descriptor namespace and those signed controls remain open.
