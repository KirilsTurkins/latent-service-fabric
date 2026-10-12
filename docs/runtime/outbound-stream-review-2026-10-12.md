# Outbound stream architecture and security review packet

This packet reconciles snapshots #912, #881 and #859 against development
`ab4e174c0599d178074e70a91947bae514eaf2f5`. It supplies concrete implementation
and evidence for [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737),
[#738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738),
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739) and
[#740](https://github.com/KirilsTurkins/latent-service-fabric/issues/740).
Their bodies and comments, including the October 8 stopped-work handoffs, were
reviewed. No independent architecture/security approval is recorded here.

## Decision submitted for independent approval

Review [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md) and the
[finite profile](outbound-stream-profile.md) against ADR-0005, ADR-0028,
ADR-0031, ADR-0059 and ADR-0060. Approve or reject the explicit supersession
scope, TLS placement, secret exposure, endpoint authority, finite limits,
unsupported operations and physical cleanup requirements. Preparatory source
and measurements do not amend the ADR's proposed status.

The default node still refuses stream installation. The explicit development
provider is TCP only. Direct host TLS remains refused by
`latent-streams::tls::ACCOUNTING_QUALIFIED`; a parsed TLS configuration grants
neither readiness nor permission. No test, package identity or generated
requirement may turn an HTTP method/path grant into opaque-byte authority.
Strict transactions continue to deny immediate stream effects.

## Source and security findings

| Boundary | Current implementation and review result |
| --- | --- |
| Endpoint and address authority | Broker stream grants select canonical host, port and transport. Existing DNS/address policy checks occur before contact and at dispatch; one selected address, no fallback or ambient proxy. Canonical and signed component denial controls exercise the actual provider. |
| Physical ownership | Original provider pools, `IoCall`, `IoTransfer`, activation budget, socket reservations and node maintenance remain the owners. No extra executor, ledger, retry, session pool or application listener is added. Cancellation acknowledgement cannot refund a pending socket. |
| TLS input | Candidate host TLS uses 1–8 protected SHA-pinned DER roots and exact configured hostname. No ambient trust, keys, certificate decompression, insecure verification, STARTTLS, resumption, 0-RTT or plaintext fallback. Protected digest/link/mode failures precede contact. |
| Allocation amplification | Genuine rustls 0.23.45 accepts 5,000 tiny certificate entries with a 393,216-byte parser peak. The captured object-count patch rejects the same input with a 384-byte peak under the unchanged 65,536-byte parser ceiling. This is parser evidence, not full connection accounting. |
| Captured patch closure | Exact public archive and original/modified source identities are retained. The previously missing QUIC call site now propagates the deframer rejection, so the five-file private crate compiles. LSF exposes no QUIC operation. Verification consumes the same bounded archive bytes it authenticated and verifies the patch document identity. Shared registry sources remain unchanged. |
| Mutation uncertainty | The bounded SMTP peer records accepted DATA mutations separately from submitted replies and never infers client confirmation. Actual stream tests retain lost-reply uncertainty and prohibit host replay. Library retry behavior remains independently observable work. |
| Shared HTTP peer | The preserved #856/#859 framing parser bounds chunked and Content-Length input, rejects ambiguous framing/headers/trailers and keeps original deadlines and byte/chunk caps. Development's later fixed-port and held-GET observation controls remain intact. No typed HTTP grant becomes raw-stream authority. |
| Protected lifecycle | Existing epoch/limit reload, durable policy revocation, exact binding adoption/publication, drain and shutdown owners remain unchanged. Trust changes still require an explicit protected restart; no authenticated session migration or silent trust adoption is introduced. |

## Current bounded execution

The pinned Linux Rust 1.97.1 helper ran 18 native stream cases, 22 daemon
stream/configuration/physical-owner cases, seven canonical component cases,
four signed component/node cases and four exact host ABI controls. All passed.
Strict Clippy passed for `latent-streams` and `latentd`, all targets/features.
The suite inventory retains all original cases and adds four TLS input/refusal/wire-limit
controls; no existing ignore or execution gate changes.

The [parser execution receipt](../testing/evidence/outbound-tls-parser-reference-2026-10-12.json)
binds the exact archive, modified sources, patch, reference, compiler, locks and
executables. It preserves the original failing allocation witness, all eight
bounded vector outcomes and zero live parser allocations after Drop. The
[maintained runner](../../tools/qualify_host_stream_tls_parser.py) builds in fresh
private directories with offline Cargo; it enables no provider.

The [SMTP fixture](outbound-stream-fixtures.md) is an independently bounded
controlled peer. Its native standard-library tests do not qualify an emitted
guest networking port. The retained
[Windows HTTP framing observation](../testing/evidence/dotnet-http-framing-windows-reference-2026-10-02.json)
keeps its original source/date and is not current Linux or .NET guest evidence.

The full Python regression ran 4,013 cases with 24 skips and no failures.
After incorporating the additional 16 framing cases, 37 shared HTTP
framing/lifetime/rendezvous/scenario/matrix controls passed on both Windows and
Linux. Their [original framing source receipt](../testing/evidence/sdk-provider-peer-framing-source-2026-10-02.json)
retains its historical identity; the new focused execution does not qualify
ordinary guest libraries or a six-language provider campaign.

## Private full-transport feasibility follow-up

A separately copied qualification source applied the authenticated bounded
parser, exposed four preserved TLS controls, and enabled its TLS gate only in
that private tree. The shipped gate remains false. All four actual
broker/provider/protected-root/TCP controls passed: transfer/EOF/retirement,
wrong hostname without fallback, stalled handshake under the original deadline,
and generation rotation retaining the pending owner until peer retirement.
The [source-labeled receipt](../testing/evidence/outbound-host-tls-private-feasibility-2026-10-12.json)
retains the original PR head, every qualification-source change, unchanged
allowances, actual executable and exact selected outcomes.

One successful exchange was observed with Heaptrack 1.4.0 and replayed through
the maintained format-3 validator. Allocation traces containing the pinned
transport symbol marker peaked at 8,878 bytes; the trust-configuration marker
peaked at 16,058 bytes. Both tagged groups retired to zero. The raw whole-process
peak remains 283,785 bytes with 46,808 bytes remaining; unmatched allocations
are not erased. The [limited attribution reader](../../tools/host_stream_tls_allocation.py)
preserves every original free, unmatched memory and completion/version refusal.
Mangled-symbol attribution, one benign exchange and profiler-inclusive RSS
cannot qualify hostile full-connection, stack or kernel memory. Full
component/operator and ordinary language matrices remain open.

The subsequent [private version matrix](../testing/evidence/outbound-host-tls-private-version-matrix-2026-10-12.json)
passes five exact controls with TLS 1.2-only and TLS 1.3-only peers. Positive
transfer/rotation cases assert the actually negotiated version. Each version
also runs five hostile wire vectors: invalid record type, oversized record
length, truncated handshake, huge declared handshake length, and 33 handshake
fragment spans. The peer observes actual closure before original memory/owner
cleanup succeeds. The retained [hostile reference](../../sdk/host-stream-tls/rustls-bounds/hostile-connection-reference.rs)
matches the executed private test body. These are real finite failure controls;
hostile allocation/stack/kernel peaks and complete component qualification are
still required before changing the shipped gate.

The five hostile wire controls were also replayed from a bounded native
Heaptrack capture. Tagged transport allocations peaked at 10,389 bytes and
tagged trust configuration at 16,058 bytes; both retained zero bytes after the
actual controls completed. The version packet retains original unmatched
whole-process allocations and the trace identity. This extends the finite
native observation; it does not establish adversarial coverage for every valid
certificate/extension/root combination or stack/kernel memory.

The private [component controls](../testing/evidence/outbound-host-tls-private-component-controls-2026-10-12.json)
then execute the real canonical resource guest against a TLS peer, followed by
a genuinely signed/admitted package through normal deployment binding, manager
admission, quotas and cells. Both perform three fresh TLS 1.3 exchanges, assert
the negotiated version and check actual Store, broker, pool, socket and original
budget retirement. The [canonical](../../sdk/host-stream-tls/rustls-bounds/canonical-component-reference.rs)
and [signed](../../sdk/host-stream-tls/rustls-bounds/signed-component-reference.rs)
references retain their executed private source. These are synthetic host
conformance fixtures; they do not qualify unchanged standard-language libraries,
external packaged operators, or production installation.

The [maximum valid private control](../testing/evidence/outbound-host-tls-private-maximum-valid-2026-10-12.json)
adds eight protected 4,096-byte DER roots (32 KiB aggregate), a verified leaf,
six intermediate CAs and root (eight entries), and the full 4,096-byte TLS 1.3
encoded stapled-extension allowance. Both TLS versions negotiate successfully,
transfer data and retire their original owners. Heaptrack transport-tagged
allocations peak at 100,796 bytes and trust-tagged allocations at 16,760 bytes;
both return to zero under the unchanged 256 KiB connection and 64 KiB trust
reservations. Whole-process peak is 390,912 bytes with 46,808 bytes remaining.
The [executed reference](../../sdk/host-stream-tls/rustls-bounds/maximum-valid-reference.rs)
and receipt preserve exact private source, executable and trace identities.
This finite maximum-shape witness supplies no general allocation bound and
does not infer stack/kernel costs or qualify ordinary clients and operators.

The [native stack observation](../testing/evidence/outbound-host-tls-private-native-stack-2026-10-12.json)
uses Valgrind 3.19.0 Massif with explicit
[`--stacks=yes`](https://valgrind.org/docs/manual/ms-manual.html).
Both the maximum valid two-version case and the five hostile wire controls pass
under their unchanged original deadlines. Retained process snapshots peak at
189,952 and 164,432 stack bytes respectively. These include the synthetic peer,
certificate generator, test harness and runtime threads; they are observed
process peaks and do not establish a connection-specific stack upper bound.

The [kernel owner observation](../testing/evidence/outbound-host-tls-private-kernel-owners-2026-10-12.json)
adds private checkpoints on the original transport. Actual Linux socket options
report 32,768 send and 65,536 receive bytes, exactly the unchanged 96 KiB logical
kernel reservation. `ss` rows match each actual socket inode before processing.
The maximum valid controls observe 33,579 receive-memory bytes and 966 queued
send-memory bytes; the hostile controls observe 1,097 receive-memory bytes.
After actual provider cleanup, `/proc/self/fd` contains none of the two positive
or five hostile socket owners. The
[observer reference](../../sdk/host-stream-tls/rustls-bounds/kernel-observer-reference.rs)
and receipt retain the exact private instrumentation and executable identities.
Checkpoints do not prove all-time kernel peaks or TCP metadata bounds; a missing
`ss` row after shutdown is never treated as descriptor retirement.

The [external development operator observation](../testing/evidence/outbound-stream-development-operator-2026-10-12.json)
packages source-built node and CLI debug executables locally and exercises them
as separate processes with synthetic protected credentials. Sixteen stages pass:
authenticated inspection and wrong-token/foreign-tenant denial; protected epoch
rotation and repeated-epoch refusal; live credential and overbroad input refusal;
explicit stream drain and clean stop; protected credential restart, old-token
refusal, fresh authenticated inspection and explicit binding publication. Both
actual processes report clean shutdown and are reaped. The dormant stream peer
receives zero contacts. This is a local development artifact with the explicit
TCP feature; it is not a released artifact or an admitted ordinary standard-API
guest workflow. The receipt retains three harness/environment failures without
turning them into product failures or erasing the original outcomes.

The first reconciliation CI head exposed a carried peer restriction that
refused nonempty GET/HEAD bodies. The existing signed guest HTTP contract sends
`payload` for GET, HEAD and POST. The peer now accepts explicitly framed bodies
under its same bounds and continues rejecting undeclared/trailing payload.
All original framing cases remain, with one added frozen-contract regression.

## Acceptance still requiring completion

| Owner | Remaining requirement |
| --- | --- |
| #737 | Independent architecture and security approval, including proposed TLS/secret placement and production enablement. An agent source audit cannot fabricate that signoff. |
| #738 | Complete allocator/stack/kernel upper-bound proof under the unchanged reservations and real-component adversarial host-TLS execution. Tagged heap peaks, process stack snapshots and finite kernel checkpoints supply only their recorded subset. |
| #739 | Admitted ordinary standard-API guest workflow with live owners, application credential/trust failure and rotation, revocation, quota/quarantine diagnostics and fresh authorized invocation on a supported packaged node. The external development process observation covers dormant configuration/authentication/rotation/drain/restart only. |
| #740 | Every promised ordinary Rust/C/Go/Java/TypeScript/.NET socket and guest-TLS entry, unchanged default client factories, private/catalogue-absent dependency, transitive worker/timer and actual physical/native measurements. Canonical TCP and native SMTP fixtures cannot replace these cells. |
| #680 | The useful positive closed WASI HTTP composition slice remains separate from the exact negative WASI socket/resource recognition controls. Unknown socket imports remain denied; import renaming supplies no adapter. |

No issue closes from this reconciliation. Historical failures, stopped-work
records and approval requirements remain visible. The packet is ready for a
reviewer to record a concrete decision against the maintained source and its
explicit unqualified boundaries.
