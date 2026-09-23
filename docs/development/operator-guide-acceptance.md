# Operator guide evidence and publication handoff

## Current acceptance status

This handoff tracks [#237](https://github.com/KirilsTurkins/latent-service-fabric/issues/237)
and its guide children against the 27 outcomes in the
[coverage contract](../../website/content/coverage-contract.json).
The September 23, 2026 integration uses development
`532364d697b1b93f2b3187e0df367f878023e91a`. Executed walkthroughs, human review
and release publication are separate requirements. Each execution record below
keeps its original source, binary and collector identities; its presence in a
later checkout does not establish execution of that checkout.

First-node, operator, provider, six-client and Angular walkthroughs have
retained execution evidence. Security monitoring is activated. Human newcomer
and maintainer reviews remain pending in the
[27-outcome review checklist](phase3-guide-review.md). Native alpha.4 has complete
compatible-version rehearsal evidence and still requires protected publication
under [#308](https://github.com/KirilsTurkins/latent-service-fabric/issues/308).

The [current integration set](../evidence/phase3-integration-35818046307/README.md)
adds exact-source results after the obsolete alpha API removals. Seventeen
coverage rows now also link the corresponding native, SDK, provider, operator,
Angular/static-site and bounded-resource observations. These additions preserve
all 27 pending review states and each older receipt's original scope.

| Guide | Available execution evidence | Remaining acceptance |
| --- | --- | --- |
| [Native release promotion](../operations/native-release-promotion.md) | [Authenticated alpha.4 rehearsal](../evidence/native-upgrade-35821200294/README.md): both real VM profiles have complete acceptance, including actual rc.2 upgrade, unsupported downgrade rejection, reboot, retained invocation and removal/recovery; the local profile also passed rootless operation. The obsolete rc.1 HTTP format is not supported. | Requalify the publication build and publish through the protected release owner; rendered guide review. |
| [Maintained security monitoring](../operations/maintained-security-monitoring.md) | [Verified activation](security-baseline-evidence.md): approved default-branch workflow, scheduled run `35586505063`, manual run `35752339515`, both maintained refs and required security aggregate. #282 is closed. | Rendered guide review. Preserve the stated limits of settings observations, permission fixtures and scanner canaries. |
| [First node](../start/first-node.md) and [capsule delivery/recovery](../learn/deliver-and-recover-a-capsule.md) | [Core guide validation](core-guide-validation.md) links actual first-node/build, operator, publication, offline-transfer and enforced-profile receipts. First-node execution covers 19 CLI commands, success and failure cases, retained deployment after restart and clean reaping. | Human walkthrough review and native-bundle installation under #308; source-based execution does not replace bundle qualification. |
| [Reconcile a policy change](../how-to/reconcile-a-policy-change.md) | [Capability-policy execution](../evidence/guide-capability-policy-2026-09-21.json): 15 actual CLI calls with persisted revocation. [Management execution](../evidence/guide-management-2026-09-21.json) separately supplies guest and HTTP/blob coverage. | Rendered/newcomer review. The policy collector itself has no guest invocations. |
| [Exercise provider failure and recovery](../how-to/exercise-provider-failure-and-recovery.md) and the local provider guides | [Provider execution summary](../evidence/provider-guide-2026-09-21.json), [management receipt](../evidence/guide-management-2026-09-21.json), and [embedding receipt](../evidence/provider-libraries-2026-09-21.json). The latter records 79 cases plus one isolated environment child, including local calls, descendant cleanup, randomness and metrics. | Rendered/newcomer review. Embedded tests, separate-node management, external-service execution and native installation retain their own boundaries. |

## Coverage outcome handoff

The table maps the existing required rows; it adds no synthetic completed rows.
All human review states remain pending until a named reviewer checks the
rendered path and records its exact revision and criteria.

| Child and existing rows | Maintained paths and evidence | Remaining acceptance |
| --- | --- | --- |
| [#357](https://github.com/KirilsTurkins/latent-service-fabric/issues/357): `evaluate-boundary`, `install-auth-readiness`, `contributor-checks`, `author-capsule`, `package-sign-publish`, `rollout-uncertain-recovery` | [Choose a path](../start/index.md), [first node](../start/first-node.md), [author a capsule](../learn/author-your-first-capsule.md), delivery/recovery and the [core execution handoff](core-guide-validation.md). | Rendered newcomer and maintainer review; final authenticated native bundle and installation evidence under #308. |
| [#358](https://github.com/KirilsTurkins/latent-service-fabric/issues/358): `client-rust`, `client-typescript`, `client-go`, `client-c`, `client-java`, `client-dotnet` | [SDK index](../../sdk/README.md) and [current six-client receipts](../evidence/phase3-integration-35818046307/README.md): 18 assertions per language, 54 activation identities, six operation receipts, 24 physically closed held requests and six clean shutdowns. Earlier guide receipts retain their original identities. | Rendered newcomer and maintainer review of each actual language path. Native client qualification does not imply browser-client or installed-bundle qualification. |
| [#359](https://github.com/KirilsTurkins/latent-service-fabric/issues/359): `grants-bindings`, `http-streaming`, `local-s3-blobs`, `local-vault-secrets`, `nats-events-triggers`, `local-calls-descendants`, `randomness-metrics`, `operator-security-recovery` | [Core/provider execution handoff](core-guide-validation.md), [external provider path](../how-to/exercise-provider-failure-and-recovery.md), [capability contracts](../runtime/capabilities.md), [provider pools](../runtime/provider-pools.md) and [security profiles](../runtime/execution-security-profiles.md). Local/HTTP/call/utility and configured-node execution records are available. | Rendered newcomer and maintainer review; retain each collector's allowed/denied/failure/cleanup scope instead of treating one receipt as universal provider coverage. |
| [#361](https://github.com/KirilsTurkins/latent-service-fabric/issues/361): `angular-build-profile`, `angular-publication-routing`, `angular-browser-workflow` | [Restricted Angular build](../component-development/angular-build.md), [renderer profile](../runtime/angular-renderer-profile.md), [runtime](../runtime/angular-renderer-runtime.md), and [actual Angular reference qualification](../testing/angular-reference-workflow.md). #372 merged as `ffa90dc3f76f4bc589be63d313103fdb67fb5f1b`; #236 is closed. | Rendered newcomer and maintainer review. Keep the supported T0/T1 boundary, unchecked reproducibility and declared incomplete dependency coverage explicit. |
| #237 umbrella: `reference-contracts`, `trust-resource-architecture`, `retained-performance-evidence`, `later-phase-boundary` | [Reference-guide evidence](../evidence/reference-guides-2026-09-21.json), implemented references and accepted architecture decisions; the [Phase 3 gate handoff](../phase-3-gate-review.md) links measured resource profiles and later-phase limits. | Rendered review of the four outcomes and completion of the child guide requirements. |

The former #366 and #344 integration checkpoints are merged. The later
six-client and Angular records above replace their old pending-work status.
They do not turn the Angular steps skipped in the historical native-parent CI
run into passes, or erase the failed Angular attempts retained alongside the
successful reference run.

## Historical receipt boundaries

The [f8d native summary](../evidence/native-runtime-f8d0c51a.json) and
[edec integrated candidate](../evidence/native-runtime-edec84fa.json) retain
their original sources, CI checkouts, VM results and missing-version-pair gaps.
The later rc.1 and rc.2 foundations are separate artifacts and do not rewrite them.

The [original operator receipt](../evidence/core-operator-walkthrough-35454985599.json)
and [original provider receipt](../evidence/provider-walkthrough-35454985599.json)
record execution at `05360c50eb6c40212111ad0d87198db5dead78a5`, for reviewed
head `edec84fa`. All 18 provider source objects matched guide source `22dc2f07`;
at `3c2f3e7d` only 17 matched because `Cargo.lock` changed. Those observations
remain historical. Use the separately dated current handoffs above for later
execution; a Markdown check or matching source fragment cannot qualify a newer
dependency graph or binary.

## Preserve runtime and authority boundaries

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

The foundation is merged; its builder consumes these current pages directly.
The existing `learn/` and `how-to/` pages belong in their matching task sidebars,
not the architecture section. The [coverage inventory](../../website/content/coverage.json)
maps maintained paths and receipts to the existing outcomes. Retain
reference-only sources as references; execution evidence alone does not
establish that a reader can complete the rendered learning path.
Keep `review.status` pending, `reviewedCommit` null and criteria unaccepted until
the actual rendered review. Evidence availability and execution are distinct.

For every essential path, review all ten contract criteria at one selected
source: outcome, version/profile, prerequisites, full source, commands, expected
observations, failure cases, cleanup, deeper reference and actual validation
level. #351/#352 supply source-backed example presentation; #353 binds source,
snippet, assets and version. Do not put copied runnable programs or a second
edited `website/docs` tree beside the authoritative `docs/` sources.

Use the foundation's pinned website toolchain and
[its complete validation instructions](website.md).
Retain the exact source and results when running these checks. This command
list is not a claim they ran at the current source or supplied human acceptance:

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
Wiki inventory, migration of useful content and removal of the Wiki after the
site is deployed and Phase 3 completes. Retire its publisher and direct readers
to the site; preserving old Wiki links or publishing archive notices is not
required. Do not merge the historical Wiki branch wholesale or edit two copies
of live prose.

The migration gate #345 consumes this reviewed content and blocks Phase 3
#201/#240. There is **no reverse dependency** on those gates closing or on a future
Phase 3 tag. Existing source-only alpha documentation and labelled development
guides can be published before phase completion, with unavailable native release
downloads and pending human reviews explicitly marked.

Stop only the owned preview/test processes; remove generated website output or
private guide-test directories only within that run's verified worktree. Preserve
historical benchmarks/receipts and never publish secrets, VM disks or backups.
For handoff, record the exact guide commit, changed paths, command/source checks,
owned walkthrough receipt identities, production-render/browser results, reviewer
and criteria, deployment identity and remaining gaps. Do not close #237 or a
child issue merely because these Markdown files exist or an earlier source's
CI/VM run was green.
