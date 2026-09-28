# Outbound streams versus typed protocol gateways

Research for [#696](https://github.com/KirilsTurkins/latent-service-fabric/issues/696),
part of the SDK library ecosystem. **Not an installed provider, guest adapter,
standalone server, or supported socket profile.** The proposed decision is
[ADR-0059](../../adr/0059-defer-general-outbound-streams.md): defer production
streams and new protocol providers, preserve existing typed capability boundaries,
and revisit a specific use case only with production qualification evidence.

## Reproduce the local experiment

From the repository root, using an already installed Go compiler and Python with
`jsonschema` (also used by repository schema validation):

```sh
python3 research/outbound-streams/run.py
python3 research/outbound-streams/run.py --verify target/outbound-streams/receipt.json
```

The runner does not download a toolchain or dependency. It disables Go modules,
workspaces, proxy/checksum lookups and automatic toolchain selection. Its finite
commands run `gofmt` verification, Go vet, race-enabled real-network tests and
five Python contract tests. A missing compiler, race prerequisite, Python package,
failed test or timeout returns nonzero **and writes failure evidence**. Source
hashes bind each receipt; `--verify` rejects edited sources. The output is a local
observation, not signed build provenance. The test-only package is opt-in and is
not added to the production SDK/workspace or a new per-ticket CI workflow.

The retained [receipt](evidence/receipt.json) identifies the actual compiler,
selected standard-library source hashes, commands, test durations, outcomes and
source hashes. The historical run used Go 1.23.2 on Linux/amd64; this is an
available laboratory compiler, **not a new LSF toolchain pin or production security
recommendation**. A different installed Go version produces a different evidence
identity. The race runtime needs its normal supported C/compiler environment.

Go's real `net/smtp` client communicates with a bounded, test-owned SMTP peer on
an ephemeral **127.0.0.1** port. No internet, real mailbox, mail relay, reusable
private key, credential or persistent application worker is used. TLS tests
create ephemeral in-memory certificates. The protocol peer validates SMTP framing
and records DATA acceptance; it is a maintained fixture, not a commercial mail
server qualification. The only injected failures are short I/O, a finite write
fault, protocol rejection, a missing reply, or a peer waiting at a witnessed
protocol boundary. Channels establish readiness; timers bound failure cleanup.

### What actually executes

`Provider.Send` takes a typed message with fixed approved sender and recipient,
not a socket descriptor, target URL or arbitrary SMTP command. A trusted exact
provider/tenant/destination/port/operation/epoch tuple is checked at bind and
again at dispatch. Handles are pointer-and-incarnation scoped, single-use, and
cannot be reused across providers or activations. Capacity and an audit slot are
reserved before the private body copy and connect. There is one active socket,
no work queue, no connection pool and no reconnect. Cancellation closes the
actual socket; its callback is joined before physical ownership is refunded.

The experiment calls `smtp.NewClient` with an injected connection. A bounded
wrapper honors `io.Writer`'s short-write contract and makes I/O failure sticky,
including against the client's EHLO-to-HELO fallback. Explicit protocol error
responses may trigger that library fallback, but do not trigger connection or
message replay. No AUTH, STARTTLS, QUIT, automatic retry or session resumption is
selected. The optional TLS mode is implicit host TLS before SMTP bytes, with an
explicit root pool, original hostname verification, minimum TLS 1.2 and no session
cache. No downgrade to cleartext follows TLS failure.

`peer-accepted` means a complete final SMTP 250 response was observed, not recipient
delivery. Other failures after attempted application writes conservatively return
`uncertain`, even a known 550 response in this intentionally narrow prototype.
Protocol-specific richer rejection evidence would be separate production work.
Before-write TLS failure is not marked as SMTP mutation, but the peer **was**
contacted. Denial before dispatch contacts nothing. This distinction is tested.

### Concrete prototype bounds

| Owner/dimension | Selected test profile / hard constructor maximum |
| --- | --- |
| Live handles | 2 provider, 1 per tenant / 8 provider |
| Queued calls, idle pool entries | 0 / 0 |
| One private message | 1..4,096 bytes; fixed approved envelope |
| Internal transport slice | 7 bytes in most tests / 4,096 bytes |
| Application read/write totals | 16 KiB each per operation |
| Raw wire read/write totals, including TLS | 64 KiB each / 128 KiB each |
| Handle metadata | 256 logical bytes each |
| Operation metadata | 16 KiB; includes a logical allowance for textproto buffers |
| Socket buffer request / logical kernel reservation | 16 KiB send, 32 KiB receive / 96 KiB |
| Additional TLS reservation | 64 KiB logical allowance, **not a proven allocator bound** |
| Shared charged live bytes | 512 KiB / 4 MiB |
| Retained audit outcomes | 32 / 128; reserve before dispatch; no payload/error strings |
| Idle / absolute lifetime | 1 second / at most 5 seconds; parent deadline may narrow |

Positive I/O can renew the idle deadline but cannot extend the original absolute
one. No new transport read is issued while synchronous consumption is blocked;
there is no unbounded async queue. The fixed provider configuration, bounded map
capacity and audit records are provider-owned metadata separate from the reported
live handle/operation counter. The counters are logical reservations, not total
allocator, kernel, GC or process RSS measurements. TLS/textproto may retain copies
outside the explicitly zeroized private body; **this is a production blocker**,
not an assertion of end-to-end secret zeroization or hostile-peer containment.

The cancellation test holds an explicit retirement barrier after the socket
cleanup. Its source-bound measurement retains one handle, one active operation
and 114,971 logical bytes until the operation is allowed to retire. It then checks
all three live counters are zero. This is a tested ownership fact, not a bound
on OS scheduling or peer-side termination. The 80 ms stall test uses an idle
expiry and a separate finite watchdog; it does not establish a production SLO.

### Reuse versus modelling

The production reuse path is
`CapabilitySession -> IoRuntime::admit_until -> IoReady -> dispatch -> IoCall`,
with the existing shared provider pool/metadata owners and original budget ledger.
See the [broker](../../docs/runtime/capability-broker.md),
[I/O substrate](../../docs/runtime/async-host-io.md),
[provider pools](../../docs/runtime/provider-pools.md) and
[HTTP provider](../../docs/runtime/outbound-http.md).

This Go experiment **models that ownership order but does not invoke the Rust
broker, Wasmtime, admission, durable audit, original/descendant ledgers, or a real
capsule**. Its public Go `Grant` structure is trusted test setup, not sealed
production authority. Putting it behind an unauthenticated HTTP handler would
be unsafe; no such handler is shipped. A production typed gateway would be called
through an already-authorized HTTP request or typed local service and would
independently authenticate/map tenant, operation and credentials on its side.

Native Go was available locally; Rust/Cargo, a checked-out production workspace,
WIT parser and real guest compiler inputs were not. Those tests are recorded as
not run, never passed. Adding unexecuted broker integration code or silently
substituting an external Go client for a Go capsule would not close this gap.
The proposal therefore does not approve a new production capability. The existing
production owner APIs are reused in the design, not claimed as execution evidence.

## Evidence and acceptance map

[requirements.json](requirements.json) maps every numbered acceptance criterion to
its documents and actual tests. [compatibility.md](compatibility.md) covers real
library APIs across all six languages and the PostgreSQL counterexample.
[stream-profile.md](stream-profile.md), [streams.wit](streams.wit), and the
[grant schema](grant.schema.json) specify the **uninstalled candidate**, not the
Go prototype's public API. They are deliberately outside `wit/platform` and
`schemas`. The schema structurally validates a disabled example; semantic host/IP
normalization and WIT parser/component conformance remain unexecuted blockers.

The retained [development negative](evidence/development-negative.json) includes
the exact superseded function and source digest from the initial failing test.
An incomplete special-address blacklist missed an IPv6 documentation range. The
fix removed public routing from the experiment rather than presenting another
partial blacklist as a production security policy. Production must reuse LSF's
complete address-policy implementation and current review, not copy this fixture.

Other retained negative results include TLS trust/hostname failure, post-write
uncertainty despite peer acceptance, limit exhaustion without connect, and missing
production/guest qualification. Research completion does not turn any of these
negative results into a library compatibility certification.
