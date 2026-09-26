# Phase 3 gate review

**Decision: pending.** This is the evidence handoff for
[#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240), not a
Phase 3 completion declaration or runtime release. The implementation receipts
below retain their original source and measurement identities. The maintainer confirmed the 27-topic guide review on September 26 and
authorized guide updates and release publication without another approval.
Fresh release-source qualification, public website deployment and native delivery
remain acceptance work. Security-monitoring activation #282, the actual Angular
reference workflow #236 and static-site delivery #495/#496/#497 are complete.
Wiki removal follows Phase 3 completion and verified website deployment.

The current completion preparation starts from development
`9b97ac8a13a3d83c228f4e5bee43e54d37da2bdf`, including all six guest SDKs and
the qualified developer workflow. The [developer handoff](development/windows-qualification-handoff.md)
retains the independently authenticated package source and complete supported-host results.
The historical runtime execution review below starts from
`6c63b68064ae44284d931e80d76d1e9012189b2b`. It does not certify a later integration
commit merely because that commit contains the same documentation.
The preceding runtime integration is development
`532364d697b1b93f2b3187e0df367f878023e91a`, reviewed on September 23, 2026.
[Full CI 35818046307](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35818046307)
passed at selected source `193d52c37635026de416feffd4a2dfd57d082451`; its actual
PR checkout and the development squash have identical Git trees. The
[preceding integration receipt set](evidence/phase3-integration-35818046307/README.md)
retains the original security, six-client, browser, provider, publication,
protected Angular, static-site and bounded resource results. Earlier receipts
below keep their original execution identities and measurement scopes.

## Repository execution review, September 23

Development `8eea5c73855530ae3fcd53e4e1ea64cf9f62ab21` passed
[full CI 35879906121](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35879906121).
The [execution review](evidence/feature-validation-2026-09-23/review.json)
records the source tree, successful jobs, intentionally skipped steps, original
artifact identities, hashes of 32 unmodified receipt/output files, and four
verified empty process streams.
Every registered active libtest name was found in the successful workspace log.
Both custom compiler harness markers and the complete supervisor case coverage
were independently checked with the maintained discovery validator.

| Implemented boundary | Result at this source | Evidence |
| --- | --- | --- |
| Core contracts, admission, scheduling, routing, durable storage, CLI and node | All 166 registered targets discovered, with 2,718 active cases. The workspace log records 2,742 passing results, including custom/subprocess results; these are not an additional population of unique cases. Separate doctest and signing-compatibility recipes pass. | [Execution index](evidence/feature-validation-2026-09-23/review.json) |
| Actual component execution and separate-node behavior | The bounded conformance workflow passes its 19 cases, covering isolation, fresh stores, budgets, cancellation, failure recovery, routing and shutdown. | [Conformance](evidence/feature-validation-2026-09-23/bounded-conformance.json) |
| Capability authority, networking and protected startup | The PR security matrix passes 27 entries in 13 groups. Compiler sandbox and supervisor harnesses also pass. The fresh local build passes all 14 protected-file tests, including the privileged foreign-owner case omitted from ordinary CI. | [Security](evidence/feature-validation-2026-09-23/security-pr.json), [local execution](evidence/feature-validation-2026-09-23/local/receipt.json) |
| HTTP, local blobs and durable policies | Separate CLI/node/provider operations pass with revocation and retained deployment selection across restart. A fresh local build passes 28 blob storage/recovery cases and 15 policy CLI calls across two node starts, including exact replay and persisted revocation. | [Provider management](evidence/feature-validation-2026-09-23/provider-management.json), [local execution](evidence/feature-validation-2026-09-23/local/receipt.json) |
| External providers and event triggers | All 19 selected S3, Vault, NATS publication and NATS trigger cases pass against their pinned real services; runner cleanup is acknowledged. This preserves each provider's declared subset and immediate-operation uncertainty. | [Provider lane](evidence/feature-validation-2026-09-23/lanes/provider.json) |
| Packaging, OCI, publication authority, rollout and recovery | Verified-TLS Zot tests and the operator, publication, offline and security-profile workflows pass. Independent publications, revoked admission and retained offline invocation are exercised. | [Operator](evidence/feature-validation-2026-09-23/operator/operator-receipt.json), [publication](evidence/feature-validation-2026-09-23/operator/publication-receipt.json), [offline](evidence/feature-validation-2026-09-23/operator/offline-receipt.json), [profile](evidence/feature-validation-2026-09-23/operator/security-profile-receipt.json) |
| Angular rendering and browser boundaries | Eight renderer selections pass. The actual Angular component passes protected T1 admission, browser hydration, staged rollout, CAS rollback and restart with retained native cache. A fresh complete reference run also passes public/authenticated browser sessions, provider denial/cancellation, canary promotion, revocation, restart and rollback. | [Renderer lane](evidence/feature-validation-2026-09-23/lanes/renderer.json), [Angular T1](evidence/feature-validation-2026-09-23/operator/angular-t1-receipt.json), [complete reference](evidence/feature-validation-2026-09-23/angular-reference/review.json) |
| Static/CSR hosting | Signed exact-digest OCI transfer, two-version browser navigation, deep-link reloads, missing-file behavior, mounted redirects, cutover, rollback and revoked/foreign authority checks pass. Static snapshots retain zero active reservations and zero granted execution-cell leases. | [Static workflow](evidence/feature-validation-2026-09-23/operator/static-site-receipt.json) |
| Existing six-language network clients | All six existing client workflows pass their shared real-node matrix. The separate new capsule-authoring tickets remain with their implementation owner. | [Client matrix](evidence/feature-validation-2026-09-23/clients/matrix.json) |
| Bounded dormant-resource regression | The small retained resource workflow passes. Large scale and performance campaigns were not rerun. | [Resource receipt](evidence/feature-validation-2026-09-23/operator/resource-receipt.json) |
| Printed first-node workflow | Eight Bash blocks from the current guide execute against a freshly built CLI, node and echo component: create/start, publish, deploy, success, declared error, durable restart, delete and stop. Preparation uses provisioned tools and a dependency cache. | [Local execution](evidence/feature-validation-2026-09-23/local/receipt.json) |

The [ignored-case execution trace](evidence/feature-validation-2026-09-23/ignored-execution-review.json)
accounts for all 150 registered ignored cases: 124 are traced to current CI
logs or successful owned integration lanes, and one additional ownership case
passes locally. The remaining 25 entries are classified individually. They
include manual 100,000-item/resource/performance collectors, Harbor and full
Angular-reference qualification, a supplied-configuration diagnostic, and child
entry points whose parent workflows retain the outcome. An absent individual
libtest line is not treated as either an executed pass or a feature failure.
The subsequent [Angular reference execution](evidence/feature-validation-2026-09-23/angular-reference/review.json)
also passes the separate fixture-export case and the full workflow. The earlier
ignored-case trace retains its original checkpoint rather than being rewritten.

The local source copy verified 4,361 Git blobs against the selected commit and
excluded the benchmark tree for these selected builds. CLI and node builds used the locked
dependency graph offline with fresh target outputs. No SDK authoring source or
ticket was changed by this review.

The complete Angular reference used the same source and rebuilt the optimized
compiler. Fixture compilation first failed because the audit copy omitted the
tracked `benchmarks/phase1/cases.json` compile-time input. That
[setup failure](evidence/feature-validation-2026-09-23/angular-reference/failed-fixture-diagnostic.log)
is retained. Restoring that one file from the selected commit allowed the
unchanged fixture exporter and full workflow to pass. Cargo rebuilt the node
during fixture preparation; this run records that resulting binary identity.
All 4,361 original source blobs and the added manifest were verified unchanged
after execution. The [unaltered workflow receipt](evidence/feature-validation-2026-09-23/angular-reference/reference-receipt.json)
records 124 CLI processes, three clean node shutdowns, reclaimed backend work,
public/authenticated Chromium sessions and zero final activation reservations.

Earlier [Harbor/network qualification](reference/oci-network-profile.md),
[resource campaigns](testing/phase3-resource-recovery.md) and
[installed-bundle VM qualification](development/native-release-gate.md) keep
their original identities. Those campaigns were not rerun or relabelled here;
the [earlier Angular attempts](testing/angular-reference-workflow.md) also remain
unchanged beside the newly executed reference workflow. Angular
compilation still reports unchecked reproducibility and incomplete declared
dependency coverage. This review covers the declared Linux x86_64 T0/T1
profiles; T2 guest-process containment and production certification remain
outside it. At that historical checkpoint, guide review, site deployment and authoring were
still pending. All six authoring tickets #544–#549 and developer workflow #559
are now closed, and the maintainer has accepted the guide review. Fresh native
publication, complete-site deployment and the final decision remain to be recorded.

## Dependency and evidence closure

| Required boundary | Verified handoff | Remaining gate condition |
| --- | --- | --- |
| Phase 2 entry gate #158 | [Phase 2 completion](phase-2-completion.md) retains its original decision, source, failures and bounded resource profiles. | Preserve the earlier evidence population. |
| Guest contracts, providers and management #202–#221, #226/#227 | [Core/provider execution handoff](development/core-guide-validation.md), [provider workflow](testing/sdk-provider-workflow.md), and [integrated security selection](testing/phase3-security.md). | Current final integration checks must remain green. |
| Six executable clients #228/#230/#260–#263 | [Six-client guide receipts](evidence/phase3-sdk-guides-35509915448/README.md): 18 assertions per language, 54 activation identities, six operation receipts and 24 physically closed held requests. | Human guide review is separate from native transport and lifecycle qualification. |
| Publication correction #264–#267 | The [security matrix](testing/phase3-security.md) binds unchanged-component corrections, independent publications/tenants, revocation, legacy ambiguity and restart authority to exact maintained cases. All four implementation tickets are closed. | Preserve exact publication selection across every API/client and the final integration. |
| Registry policy #268–#270 and decisions #271–#274 | [OCI resource qualification](testing/phase3-resource-oci.md), the integrated security selection, and the accepted versioned registry, effects, wait-ownership, isolation and freshness decisions. These tickets are closed. | #274 remains a design handoff; it does not deliver cluster routing. |
| Runtime security #277–#281 and #238 | [Source-clean manual receipt](evidence/phase3-security-2026-09-20/manual-current.json), with [checksum](evidence/phase3-security-2026-09-20/manual-current.json.sha256): 186 libtest entries, two compiler mains and four separate-node workflows. #374 merged at `2967a9a1f069aaa476e2a294137bf7843a632a88` after all 17 checks passed; #238 is closed. | #282 is closed: [activation and monitoring evidence](development/security-baseline-evidence.md) retains the approved default-branch workflow, scheduled run `35586505063`, manual run `35752339515`, both maintained refs and the required security aggregate. |
| Resource equation #239 | [Provider recovery](testing/phase3-resource-recovery.md), [renderer memory/storage](testing/phase3-resource-renderer.md), [event and child ownership](testing/phase3-resource-events.md), and OCI qualification. #376 merged after exact-head CI passed; #239 is closed. | Keep profile-specific measurements, failed attempts and unexported counters explicit. |
| Angular application/reference #44/#236 | [Actual Angular reference workflow](testing/angular-reference-workflow.md): real signed two-build publication, public/authenticated browser delivery, DOM-reusing hydration, provider denial/cancellation, canary/revocation/restart/rollback and cleanup. #372 merged as `ffa90dc3f76f4bc589be63d313103fdb67fb5f1b`; both tickets are closed. | Preserve the restricted profile, unchecked reproducibility and declared incomplete dependency coverage. Guide review #361 remains separate. |
| Static web extension #495/#496/#497 | [Contract PR #498](https://github.com/KirilsTurkins/latent-service-fabric/pull/498), [delivery PR #501](https://github.com/KirilsTurkins/latent-service-fabric/pull/501) and [CSR/static-generator workflow PR #502](https://github.com/KirilsTurkins/latent-service-fabric/pull/502) are merged; all three tickets are closed. #502 merged as `e4c9120b7d4c14220a4315bfd8e717505e37a5b4` after [CI run 35784029574](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35784029574) passed, including the actual OCI/browser qualification. | Preserve the final integrated static and SSR checks; human guide review remains separate. |
| Native distribution #308 | [Authenticated alpha.4 rehearsal](evidence/native-upgrade-35821200294/README.md) passed both real VM profiles with complete acceptance, including genuine rc.2 upgrade, unsupported downgrade rejection, reboot, retained invocation and recovery/removal; local rootless evaluation also passed. The historical source and harness are `193d52c37635026de416feffd4a2dfd57d082451`. | The earlier premature tag was removed and run 35822633436 cancelled. Publication is now authorized after completion and promotion: qualify and publish the exact final release commit, preserving the historical rehearsal separately. |
| Runbooks and guides #237/#357/#358/#359/#361 | Executed first-node, delivery, provider and six-client receipts are retained. [Guide execution PR #467](https://github.com/KirilsTurkins/latent-service-fabric/pull/467) merged after all 17 checks passed. | The maintainer review is accepted. Updated packaged setup steps, final native bundle/upgrade evidence and the published site remain to be verified. |
| Finite documentation gate #345 | Foundation, theme, diagrams, examples, version binding, discovery and initial protected Pages publication are delivered. The [coverage contract](development/website.md#coverage-is-a-review-contract-not-a-page-counter) retains 27 required outcomes. | The 27-topic maintainer review is accepted with subsequent edits delegated. Publish the updated complete site, verify live routes, and finish #356's content cutover; remove the Wiki and retire its writer after Phase 3 completion. |

The [continuous Documentation & Learning workstream](development/website.md)
stays open. Its later tasks do not enlarge the finite #345 gate.
The [27-outcome checklist](development/phase3-guide-review.md) gives the
maintainer a finite review path and records the September 26 acceptance and delegated updates.

## Fixed, active and bounded shared resources

The resource model remains fixed node runtime plus active activations plus
bounded shared caches and provider pools. Metadata and retained audit/storage
bytes can grow within configured limits; dormant applications do not acquire
dedicated processes, threads or listeners.

These observations come from two different successful bounded campaigns on the
shared Docker Desktop host. Each row links the exact raw receipt; the values
are not a universal minimum, a comparison between the two profiles, or a new
measurement of the current development head.

| Profile and phase | Dormant additions | Processes / threads / listeners | Descriptors | Observed RSS |
| --- | ---: | ---: | ---: | ---: |
| [Provider campaign: fixed](testing/phase3-resource-evidence/2026-09-20-resource-stage-recovery-08-campaign.json) | 0 | 1 / 8 / 1 | 34 | 58,589,184 bytes |
| Same provider campaign: dormant | 4 / 16 / 32 | 1 / 8 / 1 at every population | 34 | 63,045,632 / 63,176,704 / 63,700,992 bytes |
| [Two-cell Angular campaign: fixed](testing/phase3-resource-evidence/2026-09-21-renderer-memory-11-web-campaign.json) | 0 | 1 / 9 / 2 | 23 | 57,540,608 bytes |
| Same Angular campaign: dormant | 2 / 4 / 8 | 1 / 9 / 2 at every population | 23 | 125,718,528 / 125,718,528 / 125,849,600 bytes |

The provider campaign retains all 96 arrivals per provider: 56 successful blob
operations and 43 successful HTTP operations; other outcomes are retained as
failed or unfinished, not counted as throughput. Post-churn recovery succeeded.
The combined setup matrix's later compiler-path failure remains a failure;
the separately executed web matrix supplies its own successful observations.

The one-cell and two-cell renderer profiles measured a 22,413,312-byte
per-invocation Wasm memory high-water mark under a 268,435,456-byte configured
ceiling. That counter includes the JavaScript engine's linear-memory use and
does not isolate live JavaScript allocator bytes. Cancelled status lacks that
consumption field; it remains unavailable. Actual cell/queue ownership and
process reap establish cleanup.

Four versus eight dormant Angular deployments retained one component, two
packages and two independent publications. Named-file logical bytes exceeded
unique-inode logical bytes by 49,070,980 bytes in each population. The linked
storage report records the bounded, non-atomic scan and allocated bytes; it
does not claim a filesystem-wide deduplication ratio.

The OCI profiles exercised one and two concurrent operations with held peer
rendezvous, cancellation, recovery and physical retirement. Their 160-byte DNS
configuration/cache reservation is an accounting charge, not OS RSS. Retained
token/DNS bytes plateaued across the recorded cold and warm pulls.

No 100,000-deployment campaign, soak, dedicated-host latency comparison or
Docker/Kubernetes performance claim is introduced by this review. Original
receipts keep their historical pending-ticket fields; later acceptance does
not rewrite measured bytes or convert an earlier failed attempt into a pass.

## Final integration and publication checks

1. The obsolete audit, capability and policy API removals and current runtime
   fixes are merged. Preserve the successful exact-source integration above and
   its retained six-client, browser, security and cleanup receipts. Any further
   runtime change needs its own required checks and review.
2. Preserve #282's activated monitoring and scheduled-ref evidence and #308's
   successful historical native rehearsal. The maintainer has authorized
   publication after the required corrections. Complete the requirements and
   merge development into release before recreating the final tag. Qualify the resulting
   release source and verify its actual published assets through the protected
   publisher; the earlier rehearsal does not qualify later runtime changes.
3. Preserve the maintainer's accepted 27-topic review and delegated updates in
   the coverage inventory. Validate the changed packaged setup paths and report
   their execution source separately. Do not attribute later automated checks
   to the human reviewer or relabel historical execution receipts.
4. Publish that reviewed complete site through the protected exact-artifact
   flow. Record source SHA, successful push CI run/attempt, immutable artifact,
   publisher run and live deployment identity. Verify home, nested/versioned
   pages, source-backed code switching, assets, search and accessibility.
5. Complete the [Wiki content migration](development/wiki-migration.md): verify
   maintained replacement routes and switch entry links to the deployed site.
   Legacy Wiki URLs, anchors and archive notices are not required.
6. Complete the required six-language capsule-authoring extension below and
   resolve the remaining guide/runbook, documentation, static-site and native
   criteria, including removal of obsolete Phase 1/2 compatibility, then publish
   the final #240 decision with immutable evidence and accepted residual limits.
   That decision closes #201 and changes the roadmap's phase-completion status.
7. After Phase 3 completion and verified site deployment, retire the old Wiki
   writer through a reviewed change, disable the repository Wiki, verify both
   actions and close #356. This final administrative removal follows the gate;
   content migration and live site readiness remain gate prerequisites.

## Required six-language capsule authoring

The maintainer's September 23 decision requires all six existing client
languages to support creating capsules before this gate closes:

- [Rust #544](https://github.com/KirilsTurkins/latent-service-fabric/issues/544)
- [C #545](https://github.com/KirilsTurkins/latent-service-fabric/issues/545)
- [TypeScript #546](https://github.com/KirilsTurkins/latent-service-fabric/issues/546)
- [Go #547](https://github.com/KirilsTurkins/latent-service-fabric/issues/547)
- [Java #548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548)
- [C#/.NET #549](https://github.com/KirilsTurkins/latent-service-fabric/issues/549)

Each ticket requires actual language sources, typed WIT imports and exports,
guest capability APIs, a usable create/build/package/deploy/invoke workflow,
equivalent runnable examples, and real-node error, authority, cancellation,
resource and cleanup checks. The existing external client matrix and #221's
original Rust/C scope remain valid for their recorded work; they do not
complete this new guest-authoring requirement. Java and C# compiler feasibility
is part of their required delivery, not permission to omit those languages.

The implementation must preserve fresh activation state and bounded shared
resources. A dormant deployment must not own a language process, thread,
listener, persistent guest heap, execution cell or provider pool. New guest
profiles need their own validation and useful language-selectable tutorials.
Each ticket records its language's current implementation and acceptance state.
The gate requires all six authoring workflows to be complete.
Delivery evidence is retained in those tickets and their language-specific
developer qualification reports. This extension alone does not complete the
remaining gate criteria, human newcomer review or development-to-release
integration.

## Later-phase exclusions

Phase 3 capability effects are immediate external operations, not a
transactional outbox or universal exactly-once execution. Durable guest state,
transactional workflows, distributed placement and cluster routing remain
later phases. Optional isolated native compilation does not provide guest
process containment or certify hostile multitenancy. The supported Angular
recipe does not host arbitrary Node/Express servers or unrestricted Angular
CLI projects. Each security/profile document retains those boundaries.
