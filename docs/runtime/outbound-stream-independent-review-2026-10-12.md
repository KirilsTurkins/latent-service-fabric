# Outbound stream decision submitted for independent review

The [October 15 review](outbound-stream-independent-review-2026-10-15.md) adds
fresh current-source execution and dependency-drift findings. The observations
below retain their original source and date.

This is the criterion-level review packet for
[#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737),
[PR #912](https://github.com/KirilsTurkins/latent-service-fabric/pull/912) and
the [source/execution packet](outbound-stream-review-2026-10-12.md).
Production source was reconciled at `8533581d6e65e89f45c6bbbe7cd37dd7fb7a61ef`;
subsequent evidence milestones leave its production gates unchanged. The reviewer
must record the actual reviewed PR commit and receipt identities. No independent
architecture or security approval is recorded.

## Proposed decision and enablement boundary

[ADR-0061](../../adr/0061-bound-standard-outbound-streams.md) supersedes only
ADR-0059's default adapter/gateway recommendation and implementation deferral,
for a finite profile after review and implementation gates pass. Explicit
endpoint authority, no protocol inference/replay, physical retirement, strict
transaction denial and fresh activation state remain requirements.

Approve or reject the [v1 profile](outbound-stream-profile.md), canonical ABI,
unsupported operations and TLS placement. A standard language runtime must own
guest TLS when the unchanged library observes trust, pinning, client certificates
or STARTTLS. The optional host-TLS candidate is a separately selected/granted TLS
1.2/1.3 transport; it cannot replace those APIs. Neither guest TLS nor an ordinary
standard socket port is qualified by this PR.

The default node refuses stream installation. The explicit development artifact
supports TCP only. `latent-streams::tls::ACCOUNTING_QUALIFIED` remains false.
Captured parser/private qualification switches are never production installation
permission. Contract approval cannot qualify missing ports or physical costs.

## Acceptance criterion reconciliation

| #737 criterion | Concrete review inputs | Decision or remaining boundary |
| --- | --- | --- |
| Exact supersession and historical evidence | ADR-0061, ADR-0059, ADR-0060 and immutable historical research receipts; each new execution has its own source identity. | Independent architecture/security approval before production enablement. |
| Versioned operations/resources/errors | [Profile](outbound-stream-profile.md), [WIT](../../wit/platform/network/package.wit), [ABI](host-abi-profile.md), actual canonical/signed component source. | Confirm canonical async/resource semantics and unsupported operations. ABI recognition supplies no standard API adapter. |
| TLS placement, trust, client-authentication/upgrades | ADR-0061 TLS decision, [candidate accounting boundary](outbound-stream-host-tls-review.md), authenticated parser and private TLS controls. | Confirm explicit host-TLS selection and guest-visible secret ownership. Guest TLS, client-authentication/pinning and STARTTLS ports remain unavailable. |
| Typed HTTP versus opaque endpoint authority | Distinct grants, ordinary broker policy, transport/port currentness and strict transaction denial controls. | No HTTP grant conversion, generated-need permission, inference, broader fallback or session reuse. |
| DNS/address, protected roots, generations and safe audit | Existing network policy/resolver/protected loader, hostname/input failures, epoch owner and bounded diagnostics. | Confirm special-address exceptions, trust placement and fencing. Close/audit counts imply no protocol success. |
| Finite memory, suspension, ownership and quarantine | Original activation/IoRuntime/IoCall/IoTransfer/pools; unchanged limits; parser, heap, stack and inode-bound kernel observations. | Complete allocator/stack/kernel upper bounds remain open. Tagged and sampled peaks cannot justify larger reservations. |
| Uncertain mutation and retry behavior | Typed uncertainty/accepted prefix, original owners, bounded SMTP mutation/reply peer and actual lost-reply/no-host-replay controls. | Ordinary-library retries require real guest clients and independently charged attempts. No rollback or exactly-once guarantee. |
| Actual WASI/source comparison and gaps | Profile comparison, [canonical components](../../crates/latent-wasmtime/tests/outbound_streams/component.rs), [ABI controls](../../crates/latent-wasmtime/tests/generic_backend/host_abi.rs), standard Rust probe below. | Unknown WASI shapes remain denied. Renaming imports or synthetic SDK calls cannot implement the runtime port. |
| Finite six-language workload matrix | Profile freezes hardwired sockets, SMTP clients, outside-checkout dependencies and worker/timer paths. | Approve operation/compiler/runtime closure for future receipts. Native/source evidence cannot qualify another emitted runtime. |
| Separate owners and release gates | Provider #738, operator #739, conformance #740, diagnostics #679 and aggregate #694. | Each issue keeps its full criteria. Source reconciliation, CI and a contract review cannot close implementation tickets. |

## Measured feasibility and its limits

The actual bounded parser rejects the original 5,000 tiny-certificate allocation
witness. Private transport controls execute positive exchange, hostname/deadline/
epoch fencing and five hostile wire vectors in both versions. Canonical and
signed components perform actual TLS calls through normal broker/admission and
physical owners. Their private source switches remain outside production.

The maximum valid shape fills eight roots/32 KiB aggregate trust, eight verified
certificate entries and the 4 KiB encoded extension limit. Tagged transport/trust
peaks are 100,796/16,760 bytes, both retiring to zero. Raw process peak is 390,912
bytes with 46,808 remaining. This finite shape proves no universal bound across
all valid/adversarial combinations. Unmatched memory remains in the receipt.

Massif stack snapshots and socket-option/`ss` checkpoints retain real process
observations without converting them into connection upper bounds. Each actual
original TLS descriptor disappears only after cleanup. Linked receipts bind
exact private sources, patches, locks, executables, tools and traces.

The external operator observation uses separate source-built debug development
node/CLI executables in a local archive. It verifies protected configuration,
authentication, epoch rotation/refusal, drain, clean stop/reap and explicit
credential restart. The provider is dormant: no ordinary guest invocation, live
application-secret/trust rotation, saturation/quarantine or released artifact
qualification is inferred.

## Current ordinary runtime-port gaps

All six runtime-owner issues were open when inspected on October 12. Compiler
pins must come from the actual captured closure and
[maintained toolchain](../../tools/toolchain.toml); older proposed matrix versions
do not qualify a newer compiler. SMTP library rows select evidence, not authority.

| Port and normal API/workload | Current evidence boundary | Missing owner |
| --- | --- | --- |
| Rust `std::net::TcpStream` / lettre default SMTP | [Pinned standard-socket probe](../testing/evidence/outbound-standard-rust-socket-negative-2026-10-12.json) observes `Unsupported` in bounded core Wasm, with zero host imports. This actual blocker is not signed-component qualification. | [#743](https://github.com/KirilsTurkins/latent-service-fabric/issues/743): standard socket/TLS/runtime bridge. |
| C sockets/poll / libcurl SMTP | [Current C profile](../../sdk/c-guest/README.md) rejects ambient WASI sockets; no emitted default-socket client receipt. | [#744](https://github.com/KirilsTurkins/latent-service-fabric/issues/744): libc I/O/readiness and TLS closure. |
| Go `net.Dial` / SMTP / STARTTLS | [Current Go profile](../../sdk/go-guest/README.md) excludes sockets; historical native SMTP retains only its original scope. | [#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742): networking, goroutine/wait/timer and TLS ownership. |
| Java Socket/SSLSocket / Angus SMTP | [Current Java profile](../../sdk/java-guest/README.md) supplies no ambient socket port; typed HTTP is separate. | [#741](https://github.com/KirilsTurkins/latent-service-fabric/issues/741): TeaVM socket/crypto/fiber and scheduled timeout. |
| TypeScript net/tls / Nodemailer | [Current guest profile](../../sdk/typescript-guest/README.md) has no qualified Node net/tls runtime. Dependency capture/HTTP lowering are separate. | [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745): finite Node callbacks/workers/timers/TLS. |
| .NET Socket/NetworkStream/SslStream / MailKit | [Current .NET profile](../../sdk/dotnet-guest/README.md) denies ambient sockets; HttpClient and injected Stream tests cannot supply this port. | [#746](https://github.com/KirilsTurkins/latent-service-fabric/issues/746): BCL/native/TLS/Task standard networking. |

Five rows are source/profile limitations, not executed client failures or passes.
The Rust row is a negative core-Wasm observation and counts as no positive socket
cell. No all-six, guest TLS or ordinary non-HTTP compatibility claim is submitted.

## Independent decision record

External architecture and security reviewers should record their identities,
exact reviewed commit/receipt digests, approve/reject/request-changes outcome,
supersession/TLS/secret-placement conclusions and required follow-ups. Contract
approval must remain distinct from production enablement and every remaining
implementation/qualification gate. Until that record exists, ADR-0061 remains
proposed and #737 remains open.
