# Engineering records

These records support maintainer decisions and explain what was tested at a
particular revision. To start contributing, use [Contribute to LSF](../contribute/index.md).
For current runtime behavior, use [the architecture overview](../architecture/overview.md).

## Development and publication

- [Integration gate](../phase-3-gate-review.md): implementation, qualification and final publication requirements.
- [Guide review checklist](phase3-guide-review.md): the maintainer's completed review and delegated developer-workflow additions.
- [Native release gate](native-release-gate.md): installation and release qualification.
- [Website publication](website-publication.md): building and deploying the reviewed site.
- [Roadmap](../roadmap.md): planned work and dependency order.
- [NativeAOT standard HTTP implementation](dotnet-standard-http.md): source profiles, ownership and outstanding component qualification.
- [Post-alpha.5 documentation audit](documentation-audit-2026-10-14.md): exact released tree, 127 merged PRs and current guide changes.
- [Snapshot reconciliation](snapshot-reconciliation/2026-10-12/README.md): merged slices, superseded checkpoints and byte-preserved historical handoffs.
- [Rust standard runtime reconciliation](rust-runtime-reconciliation/2026-10-12/README.md), [TypeScript runtime reconciliation](typescript-runtime-reconciliation.md), [.NET resource/clock reconciliation](phase4-handoffs/2026-10-12/pr856-reconciliation.md), and [Java processors](java-runtime-reconciliation/2026-10-12/pr935.md): finite executed coverage and outstanding acceptance.

The [changes guide](../start/development-changes.md) leads application authors to
current workflows. Phase 4 gate #407 and the broader SDK library/runtime gates
remain separate from these merged slices. Detailed handoff and reconciliation
pages belong to these records rather than the contributor's setup sequence.

## Historical reports

- [Initial feasibility gate](../phase-0-completion.md).
- [Standalone runtime acceptance](../phase-1-completion.md).
- [Performance extension](../phase-1-extension-completion.md).
- [Package delivery acceptance](../phase-2-completion.md).
- [Application hosting acceptance](../phase-3-gate-review.md) and [alpha.5 publication evidence](native-release-gate.md#published-alpha5-evidence).
- The superseded September 7 feature inventory is retained in [PR #69](https://github.com/KirilsTurkins/latent-service-fabric/pull/69); use the completion reports and current guides for supported behavior.
- The September 23 orphan-code removal rationale is retained in [PR #571](https://github.com/KirilsTurkins/latent-service-fabric/pull/571); its former standalone audit page duplicated completed maintenance history.

The reports retain their original measurements, limitations and source identities.
Old reproduction commands require their recorded source revision. They do not
describe commands to run from the current checkout or require obsolete code to
remain supported.
