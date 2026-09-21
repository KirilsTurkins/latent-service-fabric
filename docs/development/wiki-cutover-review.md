# Wiki cutover review

The public Wiki cutover remains pending. This review document prepares all 26
entry-page destinations without changing the old Wiki source or its publisher.
The required essential guide reviews under #345 must be recorded before notices
are published and repository entry links switch.

The [preserved migration inventory](../evidence/wiki-migration-2026-09-20.json)
identifies source `d1035a50d2fd99b076c74dd958ca4437d909f2ec`, published Wiki
`e0cc50fe654b783f189b30a8a6f7946d66177180`, all four assets, and the archived history.
Every original page body, heading anchor, release link, diagram and publication
receipt is retained by the proposed transition.

## Website and destination observations

The live [documentation website](https://kirilsturkins.github.io/latent-service-fabric/)
reported source `80d7924a6e203b88c889f4b9bd3f6afb2f0fe48c` in its site manifest on
September 21, 2026. The reviewed route map was generated from
`acf9a3d0b150cb0be345497fe2f44f56ca30f1b5`; its 304 pages include current and
versioned documents. Those distinct source identities are not interchangeable.

Direct HTTP HEAD requests checked every distinct mapped destination. Twenty-two
entry pages have live replacements. FAQ and Glossary map to the pending runtime
identities page; the sidebar and footer map to the pending migration guide.
Those two distinct routes returned 404 and must be published and checked before
cutover. Development Workflow and Repository Map use the existing contribution
learning path; that guide links to the repository contribution contract.

| Preserved Wiki entry | Proposed maintained replacement | HTTP status on September 21 |
| --- | --- | --- |
| [Activation-Lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Activation-Lifecycle.md) | [Local activation lifecycle](../activation-lifecycle.md) | 200 |
| [Architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Architecture.md) | [LSF architecture overview](../architecture/overview.md) | 200 |
| [Capsule-Development](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Capsule-Development.md) | [Creating a capsule](../component-development/creating-a-capsule.md) | 200 |
| [Contracts-and-APIs](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Contracts-and-APIs.md) | [API surface map](../api-surface.md) | 200 |
| [Core-Concepts](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Core-Concepts.md) | [LSF architecture overview](../architecture/overview.md) | 200 |
| [Deployment-and-Routing](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Deployment-and-Routing.md) | [Embedded deployment catalog and local routing](../deployment-routing.md) | 200 |
| [Design-Governance](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Design-Governance.md) | [Architecture Decision Records](../../adr/README.md) | 200 |
| [Development-Workflow](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Development-Workflow.md) | [Operate a local node and choose a contribution](../how-to/operate-and-contribute.md) | 200 |
| [Execution-Cells](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Execution-Cells.md) | [Execution-cell architecture](../architecture/execution-cells.md) | 200 |
| [FAQ](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/FAQ.md) | [Runtime identities and recovery terms](../learn/runtime-identities.md) | 404; publication pending |
| [Getting-Started](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Getting-Started.md) | [Standalone echo quickstart](standalone-quickstart.md) | 200 |
| [Glossary](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Glossary.md) | [Runtime identities and recovery terms](../learn/runtime-identities.md) | 404; publication pending |
| [Home](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Home.md) | [Standalone echo quickstart](standalone-quickstart.md) | 200 |
| [Operator-CLI](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Operator-CLI.md) | [Operator CLI](../reference/operator-cli.md) | 200 |
| [Performance-and-Infrastructure](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Performance-and-Infrastructure.md) | [Phase 1 extension: measured results and Phase 2 handoff](../phase-1-extension-completion.md) | 200 |
| [Phase-0-Runbook](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Phase-0-Runbook.md) | [Phase 0 executable spike](../phase-0-spike.md) | 200 |
| [Phase-0-Status](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Phase-0-Status.md) | [Phase 0 completion gate](../phase-0-completion.md) | 200 |
| [Phase-1-Status](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Phase-1-Status.md) | [Phase 1 completion report](../phase-1-completion.md) | 200 |
| [Repository-Map](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Repository-Map.md) | [Operate a local node and choose a contribution](../how-to/operate-and-contribute.md) | 200 |
| [Roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Roadmap.md) | [Engineering roadmap](../roadmap.md) | 200 |
| [SDKs](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/SDKs.md) | [API surface map](../api-surface.md) | 200 |
| [Security-and-Isolation](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Security-and-Isolation.md) | [Security architecture](../architecture/security.md) | 200 |
| [State-and-Effects](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/State-and-Effects.md) | [State and effect architecture](../architecture/state-and-effects.md) | 200 |
| [Testing-and-Benchmarks](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Testing-and-Benchmarks.md) | [Benchmark evidence retention](../testing/benchmark-retention.md) | 200 |
| [_Footer](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/_Footer.md) | [Wiki migration and publication continuity](wiki-migration.md) | 404; publication pending |
| [_Sidebar](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/_Sidebar.md) | [Wiki migration and publication continuity](wiki-migration.md) | 404; publication pending |

## Proposed archive notice

After guide approval and successful destination publication, place this notice
below each retained page title, substituting that row's specific replacement.
On the sidebar and footer, place it immediately after the managed marker.
Keep the original title position required by the existing Wiki validator.

> **Archived Wiki content.** Use the linked maintained replacement for this
> topic. This retained page describes an earlier documentation snapshot; its
> release and evidence claims remain historical. Start at the documentation
> website for current development and versioned guidance.

The notice's topic link uses the generated project-base route, and its website
link uses the actual deployed home. Existing Wiki links and fragments continue
to address the retained bodies. GitHub Wiki URLs do not receive HTTP redirects
from GitHub Pages.

## Reviewed execution order

1. Merge and qualify the remaining essential guides and retain their execution
   receipts. Complete the separate human newcomer reviews required by #345.
2. Publish the reviewed development site through the existing protected exact
   artifact flow. Record the source, successful push CI run, attempt, artifact,
   publisher run and live receipt. Recheck both pending routes and every mapped
   replacement against that actual deployment.
3. Review a focused `docs/wiki` PR containing only the 26 notices. Verify removing
   the inserted notice recovers each original page byte for byte. Validate all
   26 pages, all four assets and all retained local links with the existing owner.
4. Publish the approved notices through that owner and record the actual Wiki
   commit and publication manifest. Verify all notices and destination links
   against the published Git repository, including Home, sidebar and footer.
5. Retire the old publishing workflow in a separate reviewed `docs/wiki` change,
   then switch the repository entry links to the tested site. Retain generator
   sources, diagrams, page bodies and all historical publication records.
6. Record the final before/after inventory and publication identities in the
   [migration guide](wiki-migration.md). Close #356 after these checks pass.

Future prose belongs in `docs/`. Website presentation, search, version handling
and publication belong to `website/` and its protected publisher. Historical
Wiki diagram and generator sources stay attributable; their retired writer
must not resume routine synchronization.

## Bounded rollback

Before notices are published, a failed destination check leaves the existing Wiki
entry points available. After publication, restore the prior reviewed notice
state through an ordinary reviewed revert, retaining history. If Pages needs
rollback, use its protected flow with a previously published complete artifact
and the exact currently live source. Do not move runtime tags, rewrite benchmark
receipts or promote an unfinished runtime release to perform a documentation
rollback. The pre-migration Git bundle and pinned source references remain the
archive authority throughout.
