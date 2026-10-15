# Engineering records

Use [Contribute to LSF](../contribute/index.md) to start development and the
[architecture overview](../architecture/overview.md) for current runtime behavior.
These records identify decisions, tested sources and remaining acceptance;
they do not turn a historical test into qualification of the current checkout.

## Maintained development and publication records

- [Integration gate](../phase-3-gate-review.md): implementation, qualification and publication requirements.
- [Guide review checklist](phase3-guide-review.md): completed review and delegated workflow additions.
- [Native release gate](native-release-gate.md): installation and release qualification.
- [Website publication](website-publication.md): building and deploying the reviewed site.
- [Roadmap](../roadmap.md): remaining work and dependency order.
- [NativeAOT standard HTTP](dotnet-standard-http.md): source profiles, ownership and component qualification.
- [Installed recovery qualification](../testing/installed-transaction-recovery.md): current native action and custody contracts.
- [Post-alpha.5 documentation audit](documentation-audit-2026-10-14.md): release baseline, merged-change inventory and guide maintenance.

The [changes guide](../start/development-changes.md) connects current authoring
and operating workflows. Phase 4 gate #407 and the broader SDK/runtime gates
retain their own acceptance requirements.

## Original integration and handoff records

Per-PR merge, conflict and checkpoint narratives are retained at the immutable
source below instead of published as separate current guides. Their source IDs,
failed attempts, measurements and approvals keep their original scope. Links
from maintained guides to a particular result select that exact original file.

| Area | Maintained guide | Original source record |
| --- | --- | --- |
| Transaction storage, startup, clients and recovery | [State/effects](../architecture/state-and-effects.md), [installed runtime](installed-transaction-rpc.md), [recovery qualification](../testing/installed-transaction-recovery.md) | [Phase 4 integration records](https://github.com/KirilsTurkins/latent-service-fabric/tree/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/) |
| Dependency capture and generators | [Application libraries](../how-to/add-application-libraries.md) | [SDK integration record](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/sdk-handoffs/2026-10-12/pr843-reconciliation.md) |
| Rust standard clock, TLS and thread controls | [Rust authoring](../component-development/rust-authoring.md) | [Rust qualification](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/rust-runtime-reconciliation/2026-10-12/README.md) |
| TypeScript activation runtime | [Explicit import runtime](../component-development/typescript-import-runtime-candidate.md) | [TypeScript qualification](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/typescript-runtime-reconciliation.md) |
| Java lifecycle and processors | [Server profile](../component-development/java-httpserver.md), [generators](../component-development/java-generators.md) | [Java qualification records](https://github.com/KirilsTurkins/latent-service-fabric/tree/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/java-runtime-reconciliation/2026-10-12/) |
| Angular dependency refresh | [Renderer profile](../runtime/angular-renderer-profile.md) | [Original renderer/browser qualification](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/angular-dependency-reconciliation-2026-10-12.md) |
| Earlier Java transaction and gateway integration | [Java qualification](../testing/java-transaction-qualification.md), [installed recovery](../testing/installed-transaction-recovery.md) | [Java handoff](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/testing/java-transaction-integration-handoff-2026-10-08.md), [gateway reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/testing/recovery970-reconciliation-2026-10-12.md) |

The compact JSON qualification packets referenced by maintained guides remain
in the current tree. Tooling that consumes their exact identities is unchanged.

## Historical snapshot archives

The eight PR handoff ZIPs for #850, #959, #960, #966 and #975?#978 duplicated
source already retained in Git. They are removed from the current tree after
checking all 837 member hashes and the archive bytes against source
`200c17c26b24d6bf06d8d28102362ea714c1f4eb`. The originals remain in the
[archive directory](https://github.com/KirilsTurkins/latent-service-fabric/tree/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/snapshot-reconciliation/2026-10-12/historical/),
with their exact source heads, file/member/archive digests in the
[handoff manifest](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/snapshot-reconciliation/2026-10-12/historical-handoffs.json).
The [snapshot inventory](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/snapshot-reconciliation/2026-10-12/inventory.json)
and [scanner review](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/snapshot-reconciliation/2026-10-12/historical-secret-review.json)
remain available at that same revision. Recover original bytes from that source
when needed; the archives contain historical conflict custody and stopped runs,
not current installation inputs or transferable execution approval.

## Phase acceptance reports

- [Initial feasibility gate](../phase-0-completion.md).
- [Standalone runtime acceptance](../phase-1-completion.md).
- [Performance extension](../phase-1-extension-completion.md).
- [Package delivery acceptance](../phase-2-completion.md).
- [Application hosting acceptance](../phase-3-gate-review.md) and [alpha.5 publication evidence](native-release-gate.md#published-alpha5-evidence).
- The superseded feature inventory is retained in [PR #69](https://github.com/KirilsTurkins/latent-service-fabric/pull/69); orphan-code cleanup rationale remains in [PR #571](https://github.com/KirilsTurkins/latent-service-fabric/pull/571).

Old reproduction commands require their recorded source revision. Frozen release
snapshots and the retained raw benchmark and signed/compiler evidence keep their
original bytes; they do not require obsolete implementations to remain supported.
