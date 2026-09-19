# Operator guide evidence and publication handoff

## Outcome and scope

Give the documentation and parent integration maintainers one bounded review
handoff for the native-release and maintained-security guides, without treating
reference pages, source extraction or passing Markdown checks as completed
learning paths. This is a partial delivery under
[#237](https://github.com/KirilsTurkins/latent-service-fabric/issues/237), with
the child-guide requirements below still independently reviewable.

The authoring worktree starts at native candidate
`f8d0c51a9a76bf123fa8b397fb3a0e15099cd3f5` and integrates parent source
`edec84fa` in guide merge `1ed9ef3c`. The parent subsequently squash-merges #360
as development commit `f4231d0785ca9538878d6c3c72573ed837aaa5cf` at
2026-09-19 17:16:25 UTC; guide merge `1a04aeb1` includes that development ancestry.
The reviewed head and squash have identical Git trees, not identical commits.
The [separate integrated candidate record](../evidence/native-runtime-edec84fa.json)
keeps the actual native source/harness `edec84fa`, PR CI checkout `05360c50` and
squash identity distinct. No guide-authored app, SDK, native installer or security-workflow
change is introduced here. [#370's site foundation](https://github.com/KirilsTurkins/latent-service-fabric/pull/370)
owns the single-source build/coverage implementation; other guides consume their
actual subsystem owners, not a new parallel protocol or browser test suite.

## Current guide checkpoint

| Guide | Complete source and intended outcome | Evidence available here | Still required |
| --- | --- | --- | --- |
| [Native release promotion](../operations/native-release-promotion.md) | Existing native release workflow/gate, installer and real VM harness; review a genuinely versioned foundation, pin its authenticated TAR, qualify the final version and hand publication to the parent | [Frozen f8d summary](../evidence/native-runtime-f8d0c51a.json) and [separate reviewed edec candidate](../evidence/native-runtime-edec84fa.json), actual CI/security and both VM profiles, distinct boot IDs and lifecycle/rootless receipt hashes; independent candidate attestation/hash recheck | Genuine rc.1/final artifacts and their exact-source CI, actual upgrade/downgrade VM phase, release identity, protected publication, rendered newcomer/maintainer review |
| [Maintained security monitoring](../operations/maintained-security-monitoring.md) | Existing scoped baseline, settings inventory and all-lock/SDK graph contract; distinguish configuration, registration and actual both-ref execution | [Dated read-only GitHub API receipt](../evidence/operator-release-prerequisites-2026-09-19.json), [actual integrated-source settings execution](../evidence/operator-settings-2026-09-19.json), source-checked coordinator/settings/scan contract at `edec84fa` | Default-release activation, reviewed required checks, actual manual and unchanged-lock scheduled receipts, security owner's outstanding permission/push-protection evidence, rendered review |
| [Deliver and recover a capsule](../learn/deliver-and-recover-a-capsule.md) | Existing finite CLI/node/registry workflow, actual publication/rollout/recovery identities and failure diagnosis | [Real retained operator, outage, publication and enforced-profile receipts](../evidence/core-operator-walkthrough-35454985599.json); original file hashes and eight collector Git-object matches | Fresh displayed-command/source checks, rendered newcomer review and remaining first-node/capsule-authoring paths; source-contributor evidence is not installed-bundle qualification |
| [Reconcile a policy change](../how-to/reconcile-a-policy-change.md) | Existing real CLI/node control-plane workflow; historical receipts never restore revoked authority | Actual CI log receipt: 15 CLI calls, two starts, zero guest invocations and clean policy-owner shutdown, with explicit runtime checkout identity | Rendered/newcomer review; actual guest/provider allowed/denied/failure/budget/rotation paths remain separate |
| [Exercise provider failure and recovery](../how-to/exercise-provider-failure-and-recovery.md) | Existing real TLS S3/Vault/NATS services, actual guest calls and local trigger manager; distinguish denial, rotation, possible effects, bounded ownership and recovery | [19 executed real-provider tests](../evidence/provider-walkthrough-35454985599.json), owned-cleanup confirmations and 18 matching source objects/trees, separate runtime/guide identities | Rendered/newcomer review, standalone management configuration walkthrough and remaining local/HTTP/call/utility guides; contributor embedding tests are not a separate-node client or native installation qualification |

The frozen receipt summary still records artifact source and harness as **f8d**.
It does not relabel the older diagnostic source `260c3e4e` / harness `3925d416`
as same-head or inherit results from the later integration. The edec record
separately records actual all-lock RustSec and security success, both packaged
VM profiles and the merged source relationship. Both native records retain
`acceptanceComplete:false` for the missing genuine version pair; neither is a
release trust policy. The Windows recheck authenticates downloaded data with
independently provisioned GitHub CLI/roots; it executes no downloaded installer
and claims no new VM run. Full trust inputs remain separately provisioned.

## Map the existing finite coverage rows, without declaring them complete

The foundation's [coverage contract](https://github.com/KirilsTurkins/latent-service-fabric/blob/9e8cbc418c23ef0c96c99e6f078a1eb49e9f8e80/website/content/coverage-contract.json)
has 27 required outcomes. Do not add synthetic completed rows or use a future
phase/release tag as a prerequisite for honest development documentation.
The table maps the actual issue acceptance, not a substitute checklist.

| Child and existing rows | Authoritative starting points / owning evidence | Acceptance remaining at this guide checkpoint |
| --- | --- | --- |
| [#357](https://github.com/KirilsTurkins/latent-service-fabric/issues/357): `evaluate-boundary`, `install-auth-readiness`, `contributor-checks`, `author-capsule`, `package-sign-publish`, `rollout-uncertain-recovery` | [Source quickstart](standalone-quickstart.md), [native installation](../installation.md), [capsule authoring](../component-development/creating-a-capsule.md), [delivery/recovery](../phase-2-operator-workflows.md), existing `tools/run_phase2_operator_workflow.py` and native VM harness | Real newcomer first-node/publish/invoke/error/cleanup walkthrough, capsule/package/sign/verify/publication identities and rollout/lost-response/revocation recovery at the displayed source. Native release coordination supports this work but is not the whole first-node guide. |
| [#358](https://github.com/KirilsTurkins/latent-service-fabric/issues/358): `client-rust`, `client-typescript`, `client-go`, `client-c`, `client-java`, `client-dotnet` | [SDK boundary/index](../../sdk/README.md), shared #227 and each of #228/#230/#260/#261/#262/#263; each client owner's real-node harness and #351/#352 source-backed examples | All six actual language-native build/link/setup/invoke/identity/status/cancel/deadline/uncertain-response/management-page/receipt/shutdown paths, bad auth/tenant and application failure, exact toolchains and newcomer review. No network-client acceptance from a guest binding, compilation or test double. |
| [#359](https://github.com/KirilsTurkins/latent-service-fabric/issues/359): `grants-bindings`, `http-streaming`, `local-s3-blobs`, `local-vault-secrets`, `nats-events-triggers`, `local-calls-descendants`, `randomness-metrics`, `operator-security-recovery` | [Capabilities](../runtime/capabilities.md), [provider pools](../runtime/provider-pools.md), [security profiles](../runtime/execution-security-profiles.md), [real external-provider learning path](../how-to/exercise-provider-failure-and-recovery.md), existing policy workflow, provider owners and #238 | The S3/Vault/NATS path now links actual allowed/denied, rotation, lost-acknowledgement, saturation and owned-cleanup cases. Remaining local/HTTP/call/utility paths, configured-node management and rendered newcomer review still need their own evidence; monitoring covers only security activation. |
| [#361](https://github.com/KirilsTurkins/latent-service-fabric/issues/361): `angular-build-profile`, `angular-publication-routing`, `angular-browser-workflow` | [Restricted Angular build](../component-development/angular-build.md), [renderer profile](../runtime/angular-renderer-profile.md), [runtime](../runtime/angular-renderer-runtime.md), [qualification](../testing/angular-renderer-qualification.md), maintained example and #236's actual shared-ingress/browser workflow | Displayed-source build/sign/admit/publish/deploy, immutable assets, actual browser DOM reuse/navigation, broker dependency/denial/cancellation, update/canary/rollback and failures with the delivered T0/T1 boundary. Route-fulfilled browser fixtures are not end-to-end acceptance. |
| #237 umbrella: `reference-contracts`, `trust-resource-architecture`, `retained-performance-evidence`, `later-phase-boundary` | Implemented references, accepted ADRs #267/#270/#271/#272/#273 and design-only #274; exact #239 measured evidence | Architecture/support matrix reconciliation, authority and resource/uncertainty boundaries, rendered essential-path review, historical evidence preservation and explicit later-phase limits. The new runbooks do not certify these remaining outcomes. |

Some underlying implementation tickets have their own passing evidence or merges.
That does not automatically complete a guide: select the actual displayed source,
match the owned test receipt and inspect the rendered scenario. The same rule
applies when parent integration moves beyond this authoring base.

At the guide checkpoint, [#366's real-client harness](https://github.com/KirilsTurkins/latent-service-fabric/pull/366)
still declares language participants and executed receipts pending, and
[#372's Angular reference workflow](https://github.com/KirilsTurkins/latent-service-fabric/pull/372)
still declares full published/browser/cancellation/revision qualification pending.
The retained native-parent CI run's Angular steps are **skipped**, not passed.
Do not use its compiling six-language semantic fixtures or the new CLI guides
as evidence that #358/#361's actual network/browser walkthroughs executed.

Do not collapse language lifecycle differences into a website-specific retry
policy: Rust drop, TypeScript `AbortSignal`, Go contexts, Java futures, .NET tokens
and C callbacks do not by themselves acknowledge server cancellation. Preserve
full-width numbers, presence and buffer ownership; retain original invocation
and management operation identities for uncertain-response lookup, not reinvoke.

All guide paths retain the fixed-node + active-activation + bounded-shared-pool
resource model. No dormant app gets its own process/listener/provider pool.
Package verification is not execution authority; audit observation is not durable
external action; NATS redelivery is not a transactional outbox or exactly-once
workflow. Planned distributed state/cluster/freshness semantics remain planned.

## Integrate the pages and evidence into the site

After the parent merges the required source/foundation, the coverage owner adds
these runbooks and matching JSON evidence to the applicable existing rows,
especially `install-auth-readiness`, `operator-security-recovery` and
`trust-resource-architecture`. Retain reference-only sources as references;
do not mark an entire row accepted from this partial release/activation slice.
Keep `review.status` pending, `reviewedCommit` null and criteria unaccepted until
the actual rendered review. Evidence availability and execution are distinct.

For every essential path, review all ten contract criteria at one selected
source: outcome, version/profile, prerequisites, full source, commands, expected
observations, failure cases, cleanup, deeper reference and actual validation
level. #351/#352 supply source-backed example presentation; #353 binds source,
snippet, assets and version. Do not put copied runnable programs or a second
edited `website/docs` tree beside the authoritative `docs/` sources.

Use the foundation's pinned website toolchain and
[its complete validation instructions](https://github.com/KirilsTurkins/latent-service-fabric/blob/9e8cbc418c23ef0c96c99e6f078a1eb49e9f8e80/docs/development/website.md).
These are the expected checks once that source is integrated; they are not
reported here as already executed against these new pages:

```text
python3 tools/validate_docs.py
git diff --check
cd website
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npm run build
npm run build:root
npm run browser:install
npm run test:build
npm run coverage:acceptance
```

The normal docs build reads reviewed data; it never executes arbitrary Markdown
commands, starts a node or installs six language toolchains. Native/provider/SDK/
browser walkthroughs run only in their controlled owning harnesses with private
temporary credentials. A site build or snippet extraction is not that execution.
Source/dirty flags must remain honest: a mixed-source temporary render is not
exact-head publication proof. A failing coverage-acceptance command while human
reviews remain pending is an explicit remaining gate, not something to waive.

Review root and project base paths, nested reload, native installer trust links,
version notices, failure tables and source/evidence associations in the actual
production output with #349/#350's accessible theme. A development server alone
is insufficient. Keep deployed navigation coherent with the finite outcome
inventory rather than adding an article per internal command.

## Publication, cleanup and completion record

[#355](https://github.com/KirilsTurkins/latent-service-fabric/issues/355) owns the
single protected development Pages publisher. Parent default-`release` promotion
for native/security workflows must not introduce another site writer.
[#356](https://github.com/KirilsTurkins/latent-service-fabric/issues/356) owns the
Wiki inventory, migration links and retirement of duplicate publishing; do not
merge the historical Wiki branch wholesale or edit both copies of live prose.

The migration gate #345 consumes this reviewed content and blocks Phase 3
#201/#240. There is **no reverse dependency** on those gates closing or on a future
Phase 3 tag. Existing source-only alpha documentation and labelled development
guides can be published before phase completion, with unavailable native release
downloads and unfinished client/provider profiles explicitly marked.

Stop only the owned preview/test processes; remove generated website output or
private guide-test directories only within that run's verified worktree. Preserve
historical benchmarks/receipts and never publish secrets, VM disks or backups.
For handoff, record the exact guide commit, changed paths, command/source checks,
owned walkthrough receipt identities, production-render/browser results, reviewer
and criteria, deployment identity and remaining gaps. Do not close #237 or a
child issue merely because these Markdown files exist or an earlier source's
CI/VM run was green.
