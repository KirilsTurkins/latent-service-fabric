# Wiki removal review

**Content and live-site cutover verified on 2026-09-27.** All 26 inventoried Wiki
entries have maintained destinations on the complete site. Actual HTTP checks
passed all 20 distinct routes and checked their development-version identity.
The repository Wiki remains disabled, both retired workflow registrations are
`disabled_manually`, and neither has an active writer run.

The complete site was published from `69a7b30dd89b298254a16b049180bbd9082ecdec` through
[push CI 36285745230](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36285745230), attempt 1, and
[protected publisher 36287023135](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36287023135), attempt 1.
The immutable site artifact is `10920985707`,
digest `sha256:13cbc99efb2e26e5302209f03b76f31b47c9595e2effa70969ed158804852727`; the deployed tree digest is
`sha256:446a84536f367bb04290b4fd062e1a7201fa005a230e05edd7a837e485efb748`. The original publication, live-browser, build/theme/
example/version/discovery receipts and final Wiki observations are retained in
[documentation-validation-36287023135.zip](https://github.com/KirilsTurkins/latent-service-fabric/releases/download/0.1.0-alpha.4/documentation-validation-36287023135.zip), 13,532 bytes, SHA-256
`ecfbb7f76aec1bb41c10bade136b2f8b3445512bc29e5644a22ca1175abd1834`. Its public bytes were independently verified. This
supplemental archive is separate from the native publisher's attested assets.

[PR #507](https://github.com/KirilsTurkins/latent-service-fabric/pull/507) removed the old publisher source
before this gate. The [September 26 retirement observation](../evidence/wiki-retirement-2026-09-26.json)
records the disabled registrations and Wiki setting. The newer observation
rechecks those facts; it does not claim they happened after the gate decision.

The maintainer's September 22 decision replaces the old archive-notice and
legacy-link preservation plan. Useful material belongs in current guides;
obsolete Wiki URLs, anchors and pages need not remain live. The
[migration inventory](../evidence/wiki-migration-2026-09-20.json) preserves
original sources, assets and attribution.

## Completed destination verification

The final public receipt records each maintained destination URL, status 200,
byte count and response SHA-256. It verifies the formerly absent runtime
identities and migration pages as well as every other mapped destination.
The inventory's `CONTRIBUTING.md` authority now uses the maintained
[Contribute guide](../contribute/index.md) as its website entry point for the
development-workflow and repository-map entries. The current receipt records
that mapping separately; the original inventory remains unchanged. Architecture
decisions use the site's `/decisions/` routes.
The older observations below remain historical, including their 404 results.
They are not rewritten as passes or used as proof of the newer site.

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

## Final administrative closure and future ownership

The accepted guide review, complete-site publication and all destination checks
satisfy the content prerequisites for #345 and the collective gate. After the
[Phase 3 decision](../phase-3-gate-review.md) is merged and published, recheck
the already disabled Wiki and retired writers and close #356. Do not recreate
the service to repeat its removal or publish archive notices.

Future prose belongs in `docs/`. Website presentation, search, version handling
and publication belong to `website/` and its protected publisher. Git history
and original receipts retain attribution. The retired Wiki writers must not
resume synchronization or recreate another documentation service.

## Bounded rollback

Recover the website through its protected flow using a previously published
complete artifact and the exact currently live source. Do not restore Wiki
publishing, move runtime tags or rewrite historical benchmark receipts.
