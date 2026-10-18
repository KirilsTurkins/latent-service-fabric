# Outbound stream contract owner acceptance

The repository owner selected **"Accept the reviewed contract"** on 16 October
2026 in the milestone delivery session. The public [owner-decision record on
#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737#issuecomment-6208497523)
identifies the exact decision packet merged in
[#1007](https://github.com/KirilsTurkins/latent-service-fabric/pull/1007), squash
`cda8b20ce1318837e36db9c2fba5c84020c99239`. This documentation reconciliation was prepared on 18 October.
The linked comment explicitly records the agent's transcription of the owner's
decision. The October 15 technical packet remains an agent-authored audit at its
original source and date; this later decision does not turn it into external
review or a new test run.

## Accepted scope

The architecture/security decision accepts [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md)
and the [finite v1 profile](outbound-stream-profile.md) as the bounded implementation
contract. It chooses maintained standard-runtime networking beneath unchanged
ordinary libraries, with optional developer adapters/gateways. It preserves exact
endpoint/port/transport authority, no HTTP grant conversion or protocol inference,
no hidden reconnect/replay, uncertain external effects, original resource owners
through physical retirement and fresh activation/tenant state.

The selected combinations are authorized TCP, separately qualified language-owned
guest TLS, and explicitly selected direct host TLS 1.2/1.3. Library-observable
trust, pinning, client certificates and STARTTLS require the corresponding guest
runtime; host TLS cannot silently replace them. Secret exposure, entropy,
memory/credential boundaries and unsupported operations remain exactly as reviewed.

The acceptance satisfies ADR-0061's contract-review gate. Production installation
remains disabled pending the implementation and qualification gates. This change
modifies no WIT, provider, policy, compiler/runtime selection, feature flag or grant.
`ACCOUNTING_QUALIFIED` remains false. The default node's stream restrictions and
the explicit development-only TCP feature boundary remain intact.

## Exact reviewed inputs

The decision selects the following immutable files at `cda8b20ce1318837e36db9c2fba5c84020c99239`.
The SHA-256 values identify those reviewed bytes, including their then-proposed
status text; the later acceptance/status prose is a separate documentation change.
Operation signatures, states, caps, unsupported features and TLS/authority choices
are not revised by recording acceptance.

| Reviewed input at the merged #1007 source | SHA-256 |
| --- | --- |
| [adr/0059-defer-general-outbound-streams.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/adr/0059-defer-general-outbound-streams.md) | `10d27e3a4c90a29e9dc053487fb88879b5d74ec5a7f73840c8202f227b7a6226` |
| [adr/0060-bound-invocation-scoped-concurrency.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/adr/0060-bound-invocation-scoped-concurrency.md) | `5c09e0b0be39bda6d861e84d621d9edbd5620866fb34ec0774587d774ed621b5` |
| [adr/0061-bound-standard-outbound-streams.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/adr/0061-bound-standard-outbound-streams.md) | `dbe56611e12d7fec23495f335f73b4d1691bebaf42fbf6e011f2a43a8b9d6ddb` |
| [docs/runtime/outbound-stream-profile.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/docs/runtime/outbound-stream-profile.md) | `7a1fbb8fb55e416e417335d5a5b5ddc59b74f618ca510ee03c07a3b56679e05d` |
| [wit/platform/network/package.wit](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/wit/platform/network/package.wit) | `735538103dd7ec76609a0bd998d7fcc745dc3127795dcb0171c0de4ee7a8cbb9` |
| [docs/runtime/outbound-stream-independent-review-2026-10-15.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/cda8b20ce1318837e36db9c2fba5c84020c99239/docs/runtime/outbound-stream-independent-review-2026-10-15.md) | `b679a3b1ba54040853aca86f5223ffb9f7a2d24e667323a8ae92d5e98e2da3b3` |

## Literal design-criterion reconciliation

The middle column repeats the ten criteria from #737 in issue order. Their
accepted design inputs and downstream boundaries are recorded separately from
implementation availability. This is the contract/approval prerequisite, not a
claim that the six language workloads or positive TLS have executed.

| # | Literal #737 requirement | Contract disposition and evidence boundary |
| --- | --- | --- |
| 1 | Publish the exact supersession scope: replace adapter/gateway-first guidance as the default for supported ordinary clients; retain explicit authority, no protocol inference, no hidden replay, physical retirement and no guest-owned cross-activation authenticated connection state. Leave historical receipts immutable and distinguish old observations from new tests. Obtain architecture/security review before production enablement. | Accepted in [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md#supersession-and-decision): ordinary supported clients use the maintained runtime port; adapters/gateways remain optional. Only that default and the bounded implementation direction supersede ADR-0059. Its authority, no-inference/replay, physical retirement and fresh-state prohibitions remain. The owner decision recorded above supplies the architecture/security contract disposition; production gates still apply. |
| 2 | Freeze a versioned, bounded outbound TCP and TLS compatibility profile with operations/resources, state transitions, feature/ABI identity and language-level error mappings. Cover connect, read, write, poll/readiness, cancellation, EOF, partial transfers, timeouts, shutdown/close and half-close only where supported. List concrete unsupported operations; no listeners, raw packets, implicit UDP or process-global descriptor namespace. | The [v1 operations/state/error contract](outbound-stream-profile.md#abi-operations-and-states) freezes `latent:network/streams@0.1.0`, `lsf-outbound-streams-v1`, V5 recognition, affine connection/chunk ownership, canonical async operations, partial transfers, EOF, narrower timeouts, cancellation/readiness and TCP send-half-close. Its error table and unsupported-operation list cover the requested boundary; listeners, raw packets, UDP and global descriptors remain unavailable. |
| 3 | Decide TLS placement with real default-library needs: direct TLS, guest-terminated TLS over authorized TCP, standard trust/pinning/client-certificate semantics, and protocol upgrades such as STARTTLS. Specify an exact supported combination, its memory/credential boundary and unavailable features. Host-terminated TLS must not be substituted transparently when it changes the library's certificate/pinning or protocol behavior. Any guest TLS/entropy support stays explicitly profiled and accounted. | The [TLS decision](../../adr/0061-bound-standard-outbound-streams.md#tls-decision) accepts authorized TCP with language-owned guest TLS where library trust, pinning, client-key or STARTTLS semantics require it. Separately selected host TLS is direct TLS 1.2/1.3 with explicit roots/hostname policy and no transparent substitution, client-key injection, resumption, 0-RTT or online AIA/OCSP. Guest key exposure and charged crypto/entropy/memory are explicit. Neither TLS placement gains implementation qualification here. |
| 4 | Preserve authority layers: typed HTTP method/path/header grants authorize typed HTTP only; opaque stream clients require a distinct explicit endpoint/port/transport grant. No automatic grant conversion, ambient proxy, broad egress fallback or inference of HTTP/database intent from arbitrary bytes. Generated requirements are not grants. Strict transactional execution cannot acquire immediate stream mutations through a runtime port. | The [authority contract](outbound-stream-profile.md#authority-dns-and-currentness) keeps HTTP method/path/header permission separate from exact opaque endpoint/port/transport grants. Generated requirements grant nothing. No conversion, ambient proxy/fallback or protocol inference is selected; strict transactions deny immediate stream effects. |
| 5 | Specify DNS/address validation, special-address/SSRF controls, hostname and TLS trust policy, revocation/provider generations, protected credential ownership and safe audit for opaque bytes. Reuse current address/authority code; do not repeat the incomplete private-range blacklist exposed by the original prototype. | The same contract selects existing `latent-network::AddressPolicy`, bounded resolver/answer lifetime, special-address exceptions, exact peer checks, hostname/trust policy, protected configuration and generation/currentness fences. Audit is bounded metadata with no payload or secret. The old prototype blacklist failure remains historical negative evidence, never a replacement address policy. |
| 6 | Define activation/tenant/provider caps, handle and metadata costs, guest/native/TLS/kernel buffers, backpressure, live and queued bytes, idle/absolute deadlines and finite cleanup/quarantine. Include per-logical-thread suspension through #736, freshness and no hidden connection/session reuse across activations. | The [caps and retirement contract](outbound-stream-profile.md#caps-suspension-and-physical-retirement) fixes activation/tenant/provider/process limits, handles/metadata, live/queued/cumulative bytes, socket/DNS/TLS/trust allowances, backpressure, idle/absolute deadlines, finite maintenance and quarantine. It requires per-logical-thread suspension and original owners through real destruction. Reservations are the accepted design; complete allocator/stack/kernel bounds remain #738/#740 evidence, not an inferred measurement. |
| 7 | Define normal network errors and uncertain mutations separately. A failed read, close, timer or root cancellation does not prove the peer rolled back; no invisible reconnect, protocol/session resumption or lower-layer retry. Library-level retry behavior must be observable/tested and independently authorized/charged, not falsely certified by a package catalogue. | The [error mapping](outbound-stream-profile.md#error-mapping) retains ordinary network failure separately from accepted-prefix/possible-write uncertainty. Read/close/cancel/deadline cannot establish peer rollback. No host reconnect, replay or session resumption is selected. A library retry is another observable, authorized, charged attempt, independent of package identity. |
| 8 | Compare exact standard WASI/source runtime interfaces with the chosen LSF boundary. Identify compiler/ABI/reentrancy/half-close/readiness gaps with reproducible minimal components; import renaming alone is not adaptation. Plan common host semantics with language-owned ports, not per-library clients. | The [exact comparison](../../research/standard-outbound/README.md) retains original WASI sockets 0.2.0 types and reproducible type/denial components; the [actual canonical components](../../crates/latent-wasmtime/tests/outbound_streams/component.rs) exercise the host boundary. Start/finish-connect, stream-pair/pollable lifetime, canonical reentrancy and shutdown gaps are explicit. The [reviewed runtime-port table](outbound-stream-independent-review-2026-10-12.md#current-ordinary-runtime-port-gaps) links the actual negative Rust probe and source-limited cells to #741–#746. These are common feasibility/blocker records, not successful ordinary-language socket ports or import-renaming adaptation. |
| 9 | Fix a finite cross-language workload/operation matrix for subsequent implementation and qualification, including unchanged non-HTTP clients and a hardwired socket client. Choose pinned libraries as evidence only. Normal dependency declarations, runtime-profile selection, credentials and explicit grants are allowed; injected transports, fixture-only forks or SDK calls bypassing the library cannot satisfy transparent compatibility. | The [finite matrix](outbound-stream-profile.md#exact-sourcewasi-comparison-and-finite-qualification-matrix) fixes ordinary APIs, unchanged non-HTTP/default-factory workloads, hardwired socket clients, outside-checkout/renamed dependencies and transitive worker/timer controls for all six ports. Each future receipt freezes actual selected artifacts/features and compiler/runtime/TLS closure. Named libraries select evidence, not an approval catalogue; injected transports, fixture forks and direct SDK bypasses do not satisfy the matrix. |
| 10 | Cross-link separate owners for production provider/authority integration, protected operator lifecycle and actual-component/adversarial conformance. Spell out release gates and partial-delivery boundaries so a completed design cannot close implementation tickets. If a required operation remains blocked, record the exact reproducer and missing implementation owner; do not relabel a stub or gateway-only path as fulfillment. | Owners and release gates are explicit in [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md#exact-gates-and-partial-delivery): #738 provider/authority, #739 protected operation, #740 actual-component/adversarial accounting, #741–#746 runtime ports, #679 diagnostics and #694 aggregation. Missing operations retain their reproducer/source-limit and owner links. Design acceptance cannot fulfill or close those implementation issues, and their final closure is not a dependency of this design ticket. |

## Retained feasibility and remaining implementation gates

The [October 15 review](outbound-stream-independent-review-2026-10-15.md#fresh-execution-and-source-identity)
retains the source-bound Linux Rust 1.97.1 execution of all 18 stream-provider
and seven canonical component checks, with locked dependencies and no ignored
cases. Its exact source identities and raw-log digests stay at that original
revision. This documentation work runs no native/component qualification and
creates no new execution receipt.

The earlier private TLS observations use rustls 0.23.45, while the October 15
reviewed lock uses 0.23.46. Those private receipts cannot qualify the changed
closure. Logical reservations, sampled/tagged heap peaks, stack observations and
socket checkpoints remain their recorded evidence, not complete physical bounds.
The actual Rust standard-socket negative and the other source-limited port rows
remain blockers with their original owners, rather than positive client cells.

Provider/authority #738, protected operation #739, adversarial/physical and
actual-component #740, language ports #741–#746 and aggregate #694 retain all
their acceptance. Ordinary HTTP and listener-free inbound work remain independent.
Historical #696 findings, ADR-0059/0060, review packets and receipt files keep
their original bytes.

The remaining #737 delivery is integration of this owner/status record and the
ten-point reconciliation through the normal documentation review. No new owner
approval is invented or requested for the already accepted exact contract.
Completion of this design record can complete #737 independently of downstream
implementation, and cannot make those other issues complete. Until this record
is merged, #737 remains open.
