# Outbound-stream adversarial conformance

This is the shared fixture and signed-node test owner for the
[accepted outbound profile](../runtime/outbound-stream-profile.md) and
[#740](https://github.com/KirilsTurkins/latent-service-fabric/issues/740).
It does not replace the individual language ports, the protected operator
workflow, or #694's cross-language aggregate. The
[qualification status](../runtime/outbound-stream-qualification.md) and
[kernel accounting contract](../runtime/outbound-stream-kernel-accounting.md)
retain their original evidence and outstanding gates.

## Execution boundaries

| Owner | What its execution establishes | What it does not establish |
| --- | --- | --- |
| [Gated SMTP peer](../../tools/outbound_stream_adversarial.py) and its [tests](../../tools/tests/test_outbound_stream_adversarial.py) | Real bounded loopback exchanges, controlled reply loss/reset/half-close, finite hostile responses, native Python client behavior and actual peer descriptor closure. | A signed component, any of the six language ports, guest parser/TLS bounds, provider retirement or kernel final free. |
| [Signed-node controls](../../crates/latent-wasmtime/tests/local_service/outbound/conformance.rs) in the existing `local_service` target | Signed/admitted canonical resource guests, real node/broker/provider/transport, terminal traps, resource misuse, oversized writes, partial-frame EOF, actual owner checks and subsequent fresh work. | Unchanged language libraries, cross-tenant isolation, a production installation, or measured allocator/kernel peaks. |
| Individual language and operator owners | Their exact source-bound execution receipts, interpreted within their declared scope. | A pass inherited from another language, a peer-only observation, or a historical receipt relabelled as current. |

The signed fixture uses the existing qualification provider installation and
normal package admission, activation manager, scheduler and Wasmtime backend.
Its node-load sample is the existing synthetic healthy fixture; actual quota,
authority and owner checks are not replaced. The signed source observation
includes the component builders, parent/child outbound test sources, owner
composition, network WIT and actual endpoint configuration. This is not a
whole-checkout build provenance or an independent approval.

## Finite protocol and language matrix

The accepted profile owns compiler/runtime pins and the finite default-path
workloads: Rust `TcpStream`/lettre, C POSIX sockets/libcurl SMTP, Go
`net.Conn`/`smtp.Dial`, Java `Socket`/Angus, TypeScript `net.Socket`/Nodemailer,
and .NET `NetworkStream`/MailKit. This owner adds no package allow-list and
selects no substitute runtime or version.

For this shared slice, all six ordinary-library qualification entries remain
**pending**. A passing canonical guest or native Python SMTP test cannot fill
one of those entries. Each language owner must supply its actual signed
component, exact library/transitive/compiler/port/patch/engine/ABI identities,
standard-I/O smoke, default factory execution and outside-checkout
catalogue-absent/renamed private dependency controls. Optional injected
transport tests remain separate. Host TLS production installation is still
gated; guest TLS and STARTTLS need their selected language owner and secret
permissions. The plaintext fixture does not advertise or implement STARTTLS.

## Controlled peer barriers

`GatedSmtpPeer` extends the existing `SmtpPeer`; the caller retains its selector
and drives `event()` and `check()`. It binds only loopback, starts no worker,
forwards nothing and never reconnects. The response window bounds queued data,
not allocator peak usage; generation scratch and the output copy can overlap.
The inherited connection, attempt,
command, input-line, message, output and lifetime bounds remain in force.

| Scenario | Deterministic observation | Permitted completion |
| --- | --- | --- |
| `greeting` | A connection is accepted, but no greeting bytes are queued. Only read interest remains registered until client EOF. | Release the ordinary greeting, reset, close or send half-close. |
| `mutation` | The bounded DATA parser sees the complete terminator and records the mutation hash. Its final `250` reply is withheld. | Release the reply, or lose it by close/reset/half-close without erasing the mutation. |
| `oversized-greeting` | Exactly 32 KiB is sent as one greeting line, ending in CRLF. At most 1 KiB of response output is queued at once. | The selected client must enforce its own response/parser bound; transport delivery alone is not a parser test. |
| `unterminated-greeting` | Exactly 32 KiB is sent without CRLF, then the peer stops producing output and exposes a barrier. | Explicitly terminate the line, reset, close or send half-close. |

Read `observation()["barriers"]` and release the original
`(attempt, sequence)` with `release(attempt, sequence, action)`. Release rejects
stale, mismatched, Boolean and malformed identities, inappropriate actions,
undrained earlier SMTP replies and expired original deadlines. Calling release
before the next selector check cannot resurrect an expired connection.
Releasing a gate does not renew idle or absolute deadlines. `event()` checks
expiry before accepting, receiving, parsing DATA or sending queued replies. A
ready key from an earlier selector batch cannot refresh an expired idle deadline,
commit a late mutation or send a reply after that check has retired its owner.
Stale keys after teardown are ignored without reopening or recounting descriptors.

The [deadline controls](../../tools/tests/test_outbound_stream_peer_deadlines.py)
inject clock values at dispatch boundaries while retaining real TCP descriptors.
They are not measurements of provider scheduling or hard kernel deadlines.
A queued TCP connection at listener expiry may already have completed its
handshake; refusing to accept it is not a claim of denial before network contact.

The peer's send half-close retains its read descriptor until client EOF or
explicit teardown. Reset uses Linux `SO_LINGER`; a failed control syscall is a
failure, not a recorded successful release. Watchdog expiry remains a failure
after actual descriptor closure and repeated cleanup. The bounded event journal
records numeric attempt/sequence/time and closed event categories, not protocol
payloads, addresses supplied by clients, credentials or arbitrary error text.

`acceptedConnections`, `acceptedMutations` and `sentMutationReplies` have
different meanings. A sent reply does not prove client confirmation. A new
explicit library call can create a second mutation; it does not roll back or
resolve the first. The native reference uses unmodified `smtplib.SMTP` with a
finite timeout and no application retry wrapper. This tests the peer; it does
not authorize or charge a component retry.

A peer gate is **not** a guest scheduling witness. The public observation keeps
`guestReadPendingObserved`, `providerRetirementObserved` and
`kernelFinalFreeObserved` false. A component controller must independently
observe its original operation, Store and provider owners before making those
claims. Do not convert the journal's timestamps into guest suspension or
no-concurrency overhead measurements.

## Client send half-close and retained replies

The gated peer distinguishes `recv() == b""` from destruction of the whole
connection. A client may finish sending a complete request and still receive
the reply. The `client-send-eof` event records that transport boundary; it does
not prove that the client's process, Store or provider has retired.

After client EOF, previously queued replies still drain in order. A committed
mutation remains accepted while its final reply is held. An otherwise idle
held descriptor is temporarily unregistered from the selector: EOF must not
create a permanent readable event, and an empty output queue must not create
a writable spin. The descriptor stays in the original connection table and
counts against its two-connection ceiling. Explicit release rearms only write
interest; the final drained reply, an explicit close/reset, or the original
deadline closes the actual descriptor. Neither EOF nor release extends idle
or absolute lifetime. If both send halves are closed, no read owner remains.

The finite hostile greeting likewise continues after client EOF, with its
original bounded output window. An unterminated greeting still needs the
controller's explicit release. Incomplete DATA or a partial terminator at EOF
never commits. A failed reset or watchdog expiry retains its failure even
after a parked descriptor is closed. Stale selector keys cannot reread EOF,
rearm an idle descriptor or count closure twice.

The [half-close controls](../../tools/tests/test_outbound_stream_peer_half_close.py)
exercise these transitions with real loopback sockets, including capacity
refusal while two descriptors are parked and fresh independent work after one
is actually closed. The ungated `SmtpPeer` retains its original EOF policy via
a small override hook; its existing SMTP tests remain unchanged. These are
peer-fixture controls, not component cross-tenant, parser-memory or kernel
final-free qualification. A sent reply still does not prove client confirmation.

## Signed-node regressions and reuse

The added cases exercise the existing encoded guest's terminal trap immediately
after connect, wrong-kind chunk use, repeated consumed-handle close, a write
one byte over the 16 KiB window, and zero/one/two/three-byte replies followed by
EOF. The reply cases exercise the approved TCP send half-close. They assert
actual returned byte counts rather than inventing a completed protocol frame.

The [canonical guest](../../crates/latent-wasmtime/tests/outbound_streams/component.rs)
does not execute an unconditional `unreachable` after a wrong-kind borrow or
consumed-handle close. An unexpected return, including a catchable error, returns
`4005` or `4006`, which fails the required trap assertion. Setup operation errors
return `2000 + error-code`; an unexpected write count or repeat chunk
materialization returns `3000` or `3001`. These diagnostics prevent earlier
catchable failures from masquerading as a resource rejection. The deliberate
terminal-trap scenario and the suspended cancellation/revocation scenario retain
their explicit traps. They are separate from the resource rejection checks.

Each failure/EOF case drops returned payload ownership, checks the original
node/Store/cancellation/broker/provider owners, then executes a separate fresh
same-tenant invocation on the existing one-cell fixture. That is a reuse
regression, not the required cross-tenant isolation campaign. Peer reads are
bounded to five bytes: any byte beyond the expected four-byte request fails.
The invocation and peer futures are joined in one scope; a ten-second watchdog
fails rather than detaching a peer or treating time elapsed as cleanup.

## Run and retain evidence

From a checkout, run the ordinary Python fixture controls:

```sh
python3 -m unittest tools.tests.test_outbound_stream_fixture \
  tools.tests.test_outbound_stream_adversarial \
  tools.tests.test_outbound_stream_peer_deadlines \
  tools.tests.test_outbound_stream_peer_half_close -v
```

Use the [local runner](../development/local-tests.md) and its existing
`latent-wasmtime.test.local_service` suite for the signed controls. Prepare one
fresh source-matched inventory, then select a fully qualified case under
`outbound::conformance::` with `--case`; use the same case selection for
prepare/check/run. The existing suite's normal CI discovery also includes the
new cases. No new workflow, exact ordinary-case inventory or build per fixture
is required. Preserve the actual executed revision, inventory/executable
identity, selected cases, failures and cleanup result; a runner diagnostic is
not by itself the complete #740 qualification report.

Source presence and a passing peer test do not assert that the Rust controls
compiled or executed. Retain hosted signed-node results before crediting those
rows. Report missing runs as pending, not successful skips. Original historical
receipts stay attributed to their original source.

## Remaining completion gates

The full issue still requires implementation-backed language/default-path
receipts, supported TLS/trust/credential isolation, protected operator rotation,
all specified authority/handle/queue/timer/resource failures, fresh cross-tenant
work, and physical guest/native/TLS/kernel peak and scheduling measurements.
The shared controls above do not waive those requirements or enable production
installation. In particular, bounded wire responses do not bound an arbitrary
guest parser, logical memory charges are not allocator/RSS measurements, and
local EOF/descriptor closure is not a kernel final-free certificate.
