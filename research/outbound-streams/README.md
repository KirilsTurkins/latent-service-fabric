# Outbound streams versus typed protocol gateways

Research for [#696](https://github.com/KirilsTurkins/latent-service-fabric/issues/696),
part of the SDK library ecosystem. **Not an installed provider, guest adapter,
standalone server, or supported socket profile.** The proposed decision is
[ADR-0059](../../adr/0059-defer-general-outbound-streams.md): defer production
streams and new protocol providers. The [second-pass investigation](deepening.md)
adds real-broker regression coverage, strict SMTP reply bounds and stronger
receipt validation without claiming production enablement.

## Reproduce the local experiment

Use an already installed Go compiler and Python with `jsonschema`, from the
repository root. A full research run includes Go tests and eleven Python checks:

```sh
python3 research/outbound-streams/run.py
python3 research/outbound-streams/run.py --verify target/outbound-streams/receipt.json
```

To reproduce the **executed second-pass native profile**, which excludes the five
schema/acceptance-map tests, use:

```sh
python3 research/outbound-streams/run.py --native-only --output target/outbound-streams/native.json
python3 research/outbound-streams/run.py --verify target/outbound-streams/native.json
python3 research/outbound-streams/run.py --verify research/outbound-streams/evidence/deepening-receipt.json
```

The retained [second-pass receipt](evidence/deepening-receipt.json) records **20
top-level Go tests, 63 cases including subtests, six Python evidence checks, Go
vet and formatting**, with no skipped cases. It includes all sixteen original Go
tests. Native means a host Go executable, **not a Go capsule**. It neither runs nor
claims the Rust regression, WIT parser, guest compilation, production DNS/secret
conformance or complete repository CI. Those boundaries are recorded in `notRun`.
The current full research profile is available but was not rerun in that receipt.

The runner disables Go modules, workspaces, proxy/checksum lookups and automatic
toolchain selection. No compiler or dependency is downloaded. Receipts record
actual commands, source hashes, tool identity and test durations; they are not
signatures or execution attestations. Verification recomputes the selected input
set, checks all top-level Go test identities across all `*_test.go` files, rejects
skips/duplicates, requires the race-test command profile and checks Python counts.
It cannot certify unexecuted branches or prove authenticity of an arbitrary
caller-authored receipt. Negative subprocess exits are retained as failures.

The original [v1 receipt](evidence/receipt.json) and
[address-policy negative](evidence/development-negative.json) remain immutable
history from commit `1a91f79f254e3484b514b2b142e7e05d0e240881`. Use that revision's
runner to verify that receipt. The current v2 verifier rejects v1 rather than
misrepresenting the old source/test set as current. Both observed native runs used
Go 1.23.2 on Linux/amd64; this is a laboratory identity, **not a new LSF pin or a
production security recommendation**. The race runtime needs its normal supported
C/compiler environment.

## What the native prototype executes

Go's real `net/smtp` client communicates with a bounded, test-owned SMTP peer on
an ephemeral **127.0.0.1** port. No external mail, real credentials, persistent
application worker or reusable private key is involved. TLS cases generate
in-memory certificates. Peers record DATA acceptance before optional lost replies;
channels witness readiness and timers are finite failure watchdogs. Parser-only
comparisons additionally use joined `net.Pipe` peers, not claimed as TCP tests.

`Provider.Send` accepts a typed message with fixed sender and recipient, not an
arbitrary target or SMTP command. Bind and dispatch check an exact trusted
provider/tenant/destination/port/operation/epoch tuple. Affine pointer/incarnation
handles reject copying, cross-provider use and stale reuse. Metadata, private body
and an audit slot are reserved before connect. One socket belongs to the active
operation; no queue, retry, reconnect or cross-activation pool is created.
Cancellation closes the actual socket and joins its callback before refund.

The injected transport honors short-write semantics and sticky I/O failure.
A [complete-line reply owner](reply_bounds.go) now bounds text passed to the
standard parser. It withholds invalid or unterminated lines instead of returning
a partial successful-looking prefix alongside an error. The retained
[failed first attempt](evidence/deepening-negative.json) explains why byte counting
alone was insufficient. Explicit valid protocol errors may cause the library's
EHLO-to-HELO fallback; framing/transport failures cannot perform further writes.
There is no AUTH, STARTTLS, QUIT, session resumption or message replay.

Optional implicit TLS precedes SMTP bytes and requires an explicit root pool,
original hostname validation and TLS 1.2 minimum. TLS failure never downgrades.
`peer-accepted` means a complete final SMTP 250 was observed, not recipient delivery.
All other failures after attempted application writes conservatively remain
`uncertain`, including the known 550 fixture. Denial means no connect; before-write
TLS failure means the TCP/TLS peer was contacted but no SMTP command was sent.

## Current prototype bounds

| Owner/dimension | Selected test profile / hard constructor maximum |
| --- | --- |
| Live handles | 2 provider, 1 per tenant / 8 provider |
| Queued calls, idle pool entries | 0 / 0 |
| Private message | 1..4,096 bytes; fixed approved envelope |
| Internal transport slice | 7 bytes in most tests / 4,096 bytes |
| Application read/write totals | 16 KiB each per operation |
| Raw wire read/write totals, including TLS | 64 KiB each / 128 KiB each |
| SMTP reply line | 512 bytes including CRLF, one fixed retained line |
| SMTP multiline reply | 16 lines, 8 KiB total, matching status prefixes |
| Handle metadata | 256 logical bytes each |
| Operation metadata | 32 KiB parser/copy allowance, reserved before connect |
| Socket buffer request / logical kernel reservation | 16 KiB send, 32 KiB receive / 96 KiB |
| Additional TLS reservation | 64 KiB logical allowance, not a proven allocator bound |
| Shared charged live bytes | 512 KiB / 4 MiB |
| Retained audit outcomes | 32 / 128; no payload/error strings |
| Idle / absolute lifetime | 1 second / at most 5 seconds; parent may narrow |

Positive I/O can renew idle time but cannot extend the original absolute deadline.
The line owner uses deliberately conservative one-byte transport reads and has no
read-ahead queue; no throughput claim is made. Fixed configuration, maps and audit
storage remain bounded provider-owned metadata distinct from live operation
counters. Kernel/allocator/GC/TLS memory is not proven by these logical allowances.
The private body and reply buffer are cleared; complete secret-copy zeroization
inside the Go library/runtime is not established.

At the controlled cancellation retirement barrier, the new measured charge is
**one handle, one active operation and 131,355 logical bytes**, then all three
counters return to zero after retirement. The historical 114,971-byte value is
unchanged in the old receipt; the 16 KiB difference is the increased parser
reservation. Neither value proves peer rollback or OS scheduling latency.

## Production broker boundary

The [Rust regression](../../crates/latent-http/src/tests/gateway_boundary.rs)
uses the actual broker, original activation ledger, `IoRuntime`, provider pools
and HTTP provider with a controlled local HTTP peer. It extends the existing
registered `tests::http::lost_mutation_reply_is_uncertain_and_never_retried` case:

```sh
cargo test -p latent-http --lib --locked tests::http::lost_mutation_reply_is_uncertain_and_never_retried -- --exact --nocapture
```

It checks cancellation after the peer records an effect, host-owner reclamation
while the external owner remains live, and a successful fresh independent
activation. Peer tasks are owned by a `JoinSet`; failure does not detach them.
See [deepening.md](deepening.md) for the precise scope and source-bound CI identity.
This is neither a new SMTP host provider nor an end-to-end Wasmtime-to-SMTP gateway.
Its controlled peer is not the Go SMTP prototype. Passing the two separately must
not be presented as passing their composition. An HTTP grant cannot authorize a
raw downstream socket, and host cleanup cannot prove external cleanup.

The Go `Grant` is still test setup, not sealed authority. Any externally operated
gateway must independently authenticate tenant/operation, bind downstream
credentials and enforce its own deadline, admission, cancellation and cleanup.
Do not expose the Go model as an unauthenticated HTTP handler. Moving it into
another capsule would not create missing compiler or transport support.

## Design and acceptance evidence

[requirements.json](requirements.json) maps the original nine acceptance criteria.
The [second-pass map](deepening.md#acceptance-delta) adds concrete boundary and
parser evidence. [compatibility.md](compatibility.md) reviews all six language
API seams and PostgreSQL constraints; it is not six guest compile qualification.
[stream-profile.md](stream-profile.md), [streams.wit](streams.wit), and the
[grant schema](grant.schema.json) remain **uninstalled research proposals**, outside
production WIT and schemas. Schema structure is not semantic DNS/IP validation;
WIT text is not a parser or runtime conformance result.

See the production [broker](../../docs/runtime/capability-broker.md),
[I/O owners](../../docs/runtime/async-host-io.md),
[provider pools](../../docs/runtime/provider-pools.md) and
[HTTP provider](../../docs/runtime/outbound-http.md) for existing contracts.
Ordinary library and HTTP adapter delivery remains independent. No new production
direction, operator workflow, capability or dependency on sockets is approved here.
