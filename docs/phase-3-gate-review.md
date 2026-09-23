# Phase 3 gate review

**Decision: pending.** This is the evidence handoff for
[#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240), not a
Phase 3 completion declaration or runtime release. The implementation receipts
below retain their original source and measurement identities. Required guide
reviews, public website deployment and native delivery
remain acceptance work. Security-monitoring activation #282, the actual Angular
reference workflow #236 and static-site delivery #495/#496/#497 are complete.
Wiki removal follows Phase 3 completion and verified website deployment.

This review starts from development
`6c63b68064ae44284d931e80d76d1e9012189b2b`, after the integrated security and
guide-execution changes were merged. It does not certify a later integration
commit merely because that commit contains the same documentation.
The current runtime integration is development
`532364d697b1b93f2b3187e0df367f878023e91a`, reviewed on September 23, 2026.
[Full CI 35818046307](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35818046307)
passed at selected source `193d52c37635026de416feffd4a2dfd57d082451`; its actual
PR checkout and the development squash have identical Git trees. The
[current integration receipt set](evidence/phase3-integration-35818046307/README.md)
retains the original security, six-client, browser, provider, publication,
protected Angular, static-site and bounded resource results. Earlier receipts
below keep their original execution identities and measurement scopes.

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
| Native distribution #308 | [Authenticated alpha.4 rehearsal](evidence/native-upgrade-35821200294/README.md) passed both real VM profiles with complete acceptance, including genuine rc.2 upgrade, unsupported downgrade rejection, reboot, retained invocation and recovery/removal; local rootless evaluation also passed. The selected source and harness are `193d52c37635026de416feffd4a2dfd57d082451`. | [Publication run 35822633436](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35822633436) independently qualifies its rebuilt archive, requires protected maintainer review and must retain verified public asset evidence. |
| Runbooks and guides #237/#357/#358/#359/#361 | Executed first-node, delivery, provider and six-client receipts are retained. [Guide execution PR #467](https://github.com/KirilsTurkins/latent-service-fabric/pull/467) merged after all 17 checks passed. | Native bundle/upgrade evidence under #308, rendered newcomer walkthroughs and maintainer pedagogy review remain required. |
| Finite documentation gate #345 | Foundation, theme, diagrams, examples, version binding, discovery and initial protected Pages publication are delivered. The [coverage contract](development/website.md#coverage-is-a-review-contract-not-a-page-counter) retains 27 required outcomes. | Complete their exact-revision human reviews, publish the complete reviewed site, verify live routes, and finish #356's content cutover; remove the Wiki and retire its writer after Phase 3 completion. |

The [continuous Documentation & Learning workstream](development/website.md)
stays open. Its later tasks do not enlarge the finite #345 gate.
The [27-outcome checklist](development/phase3-guide-review.md) gives the
maintainer a finite review path without changing any pending review status.

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
2. Preserve #282's activated monitoring and scheduled-ref evidence. The native
   compatible pair and installer/upgrade rehearsal are qualified; complete
   #308's protected publication and verification of the actual public assets.
3. Have the named reviewers execute the rendered guide paths at an exact source
   revision. Record each required outcome, expected failure, cleanup, version
   and reviewer in the coverage inventory. Automation cannot create a human
   review identity or mark a walkthrough that did not occur as reviewed.
4. Publish that reviewed complete site through the protected exact-artifact
   flow. Record source SHA, successful push CI run/attempt, immutable artifact,
   publisher run and live deployment identity. Verify home, nested/versioned
   pages, source-backed code switching, assets, search and accessibility.
5. Complete the [Wiki content migration](development/wiki-migration.md): verify
   maintained replacement routes and switch entry links to the deployed site.
   Legacy Wiki URLs, anchors and archive notices are not required.
6. Resolve the remaining guide/runbook, documentation, static-site and native
   criteria, including removal of obsolete Phase 1/2 compatibility, then publish
   the final #240 decision with immutable evidence and accepted residual limits.
   That decision closes #201 and changes the roadmap's phase-completion status.
7. After Phase 3 completion and verified site deployment, retire the old Wiki
   writer through a reviewed change, disable the repository Wiki, verify both
   actions and close #356. This final administrative removal follows the gate;
   content migration and live site readiness remain gate prerequisites.

## Later-phase exclusions

Phase 3 capability effects are immediate external operations, not a
transactional outbox or universal exactly-once execution. Durable guest state,
transactional workflows, distributed placement and cluster routing remain
later phases. Optional isolated native compilation does not provide guest
process containment or certify hostile multitenancy. The supported Angular
recipe does not host arbitrary Node/Express servers or unrestricted Angular
CLI projects. Each security/profile document retains those boundaries.
