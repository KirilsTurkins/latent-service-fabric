# Current outbound contract review

This agent-authored technical review addresses all ten criteria of
[#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737).
It submits a concrete decision for the architecture/security decision owner;
it records no human or external approval. Production enablement remains disabled.

## Reviewed decision

Accept [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md) and its
[finite v1 contract](outbound-stream-profile.md) as the implementation contract.
Supersede only ADR-0059's adapter/gateway default and implementation deferral for
qualified profiles. Preserve explicit authority, no protocol inference or hidden
replay, physical retirement and fresh activation/tenant state. Historical research
and receipts remain immutable. Contract approval cannot enable the provider or
close #738, #739, #740, any language port or #694.

The selected TCP port preserves ordinary library constructors. Guest TLS is owned
by each qualified language runtime when trust, pinning, client authentication or
STARTTLS is visible to the library. Any granted guest client key is exposed to
the capsule and must be accounted. Separately selected host TLS is direct TLS
1.2/1.3 with protected roots and hostname verification; it cannot transparently
replace those guest APIs. No resumption, 0-RTT, online AIA/OCSP or implicit client
key injection is selected. Neither TLS combination is currently qualified.

## Criterion review

| Criterion | Finding |
| --- | --- |
| Exact supersession | ADR-0061 names the replaced guidance and preserved prohibitions. Contract approval and production qualification are separate gates. |
| Versioned operations and errors | `latent:network/streams@0.1.0`, `lsf-outbound-streams-v1` and V5 ABI cover connect, finite reads/writes, readiness, inspection, TCP send-half-close and close. Affine chunks and one pending operation per direction/readiness constrain ownership. Partial transfer, EOF, cancellation, ordinary failure and uncertainty remain distinct. Listening, UDP, raw packets and a global descriptor namespace are unavailable. |
| TLS placement | The selected combinations above preserve library-observable semantics. The host-TLS gate remains false; a parsed configuration or private experiment grants no readiness. |
| Authority | Typed HTTP grants remain separate from opaque endpoint/port/transport grants. There is no proxy discovery, grant conversion, address fallback or inferred protocol. Strict transactions deny immediate stream effects. Generated requirements describe needs without granting them. |
| DNS, trust and fencing | Existing `AddressPolicy`, bounded DNS, currentness before contact/dispatch and exact peer-address checking are reused. Protected roots are digest-bound and public audit contains no credentials or payloads. Revocation/provider generations remain pinned through physical retirement. |
| Resources and suspension | Original activation/tenant/provider pools and IoRuntime owners remain responsible. The contract caps 16 KiB chunks, four live chunks, two connections/activation, 32 cumulative attempts and 2 MiB transfer. It specifies 96 KiB socket, 64 KiB DNS, 256 KiB TLS and 64 KiB trust reservations plus metadata, deadlines, bounded maintenance and quarantine. These are proposed reservations; complete physical upper bounds remain a qualification gate. Waiting must release Store borrows, retain physical owners and drain under #736. |
| Mutation uncertainty | Failed read/close/deadline/cancellation does not establish peer rollback. No host reconnect/replay occurs. Library retries require independent authorization, charging and observed peer contacts/mutations. |
| WASI/source comparison | The profile compares exact WASI start/finish-connect, stream-pair and pollable semantics with canonical async calls and affine charged chunks. Unsupported operations are denied. Existing minimal component controls establish host behavior; no import renaming is treated as a runtime port. |
| Finite workload matrix | All six language rows name ordinary socket APIs, a non-HTTP client and compiler/runtime/TLS ownership. Outside-checkout catalogue-absent dependencies, a hardwired socket client and transitive worker/timer are required. Selected artifacts/features must be captured; no injected transport or fixture fork counts. Go's maintained compiler pin is refreshed to 1.27.2; historical Go observations retain their original versions. |
| Owners and release gates | #738 owns provider/authority, #739 protected operation, #740 actual components and physical/adversarial qualification, #679 diagnostics and #694 aggregate evidence. #741-#746 own the respective runtime ports. Missing operations stay pending with reproducer/owner links in the earlier review packet. |

## Fresh execution and source identity

Reviewed development is `6f637e989864766ab298f902ada3d331d9959d29`.
The tests ran from `a3bc5dfdbbd618a11d2c13f91e465de1e1bf81f5`; the selected
ADR, WIT, outbound research/profile, stream provider, capability, policy, Wasmtime
and daemon sources have no difference between those commits.

The pinned Linux Rust 1.97.1 source run passed all 18 `latent-streams` all-feature
tests and all seven `latent-wasmtime --test outbound_streams` tests, without
ignored cases. The commands retain `--locked` and `--test-threads=1`. They cover
actual TCP/DNS cancellation, policy revocation, retained chunks/owners, expiry,
partial transfers/EOF/send-half-close, lost mutation replies without replay,
unqualified TLS refusal, canonical resources and cancellation/Store cleanup.
These are host/component fixtures, not signed ordinary-library runtime ports.

Raw log SHA-256 identities are
`ee84f9a753150eb4d575e63ac27d05bac6ac7aaf0826b7e1c8e352233ae8e98f`
for the provider run and
`e88d9348b815606f3added15a5c8ed866fa0ae583c640648581313f15dd844b0`
for the component run. No signed-node, positive TLS, language socket, released
artifact or complete native/kernel allocation claim follows from those runs.

## Required follow-ups

The October 12 private TLS receipts bind rustls 0.23.45. The current lock selects
0.23.46. They cannot qualify the changed dependency closure. Keep
`ACCOUNTING_QUALIFIED = false` until fresh complete accounting, hostile-wire,
protected lifecycle and actual-component receipts satisfy #738-#740. Finite peaks
are observations, not universal allocator/stack/kernel bounds.

Each ordinary runtime port remains independently pending. In particular, source
or native SMTP observations do not qualify guest TLS, and the negative Rust
standard-socket probe is not a successful signed component. New Java HTTP and Go
scheduling slices do not establish raw sockets or SMTP compatibility.

The architecture/security decision owner must record approve, reject or requested
changes against this exact contract and the reviewed source identities. An agent
source audit cannot supply that approval. Until a decision is recorded, ADR-0061
remains proposed and #737 remains open.
