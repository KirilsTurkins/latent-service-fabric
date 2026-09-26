# Wiki removal review

The repository Wiki is disabled. [PR #507](https://github.com/KirilsTurkins/latent-service-fabric/pull/507)
already removed its publisher from `docs/wiki`, and the remaining bootstrap and
publisher registrations were disabled on September 26. The
[retirement observation](../evidence/wiki-retirement-2026-09-26.json) confirms both
registrations and zero active writer runs. The complete-site deployment and
replacement-route checks still need their final receipt before #356 closes.

The maintainer decision of September 22 replaces the earlier plan to publish
26 archive notices and preserve legacy navigation. Useful material belongs in
current guides; old Wiki URLs, anchors and obsolete pages need not remain live.

The [migration inventory](../evidence/wiki-migration-2026-09-20.json) records source
`d1035a50d2fd99b076c74dd958ca4437d909f2ec`, published Wiki
`e0cc50fe654b783f189b30a8a6f7946d66177180`, all four assets and historical identities.
These pinned references establish attribution without retaining an active Wiki.
The route observations below are historical checks, not proof of a completed
website cutover. The newer retirement observation does not change their results.

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

| Inventoried Wiki entry | Content destination | HTTP status on September 21 |
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

## Execution order

1. Preserve the accepted September 26 guide review and qualify subsequent guide
   corrections. The maintainer delegated those updates without another approval.
2. Publish the reviewed development site through the protected exact artifact
   flow. Record source, successful push CI run, attempt, artifact, publisher run
   and live receipt. Recheck every maintained destination, including the two
   routes that were absent at the historical observation above.
3. Switch repository and public entry links to the tested site and remove active
   Wiki navigation. Obsolete page content can be retired rather than copied.
4. Complete the Phase 3 gate using the content migration, guide reviews and live
   website evidence. Keep the actual earlier source-removal and settings
   observations; do not claim that those actions happened after this decision.
5. Recheck the disabled Wiki, retired workflow registrations and maintained entry
   links. Do not recreate or re-enable the old service to repeat its removal.
6. Record the resulting site/source identity and Wiki removal receipt in the
   [migration guide](wiki-migration.md), then close #356. Publishing archive
   notices, preserving legacy links or maintaining redirect pages is unnecessary.

Future prose belongs in `docs/`. Website presentation, search, version handling
and publication belong to `website/` and its protected publisher. Git history
and original evidence receipts retain attribution. The retired Wiki writer must
not resume synchronization or recreate a second documentation service.

## Bounded rollback

A failed live destination check delays cutover until the site is corrected.
After removal, recover the website through its protected flow with a previously
published complete artifact and the exact currently live source. Do not restore
Wiki publishing, move runtime tags or rewrite historical benchmark receipts.
