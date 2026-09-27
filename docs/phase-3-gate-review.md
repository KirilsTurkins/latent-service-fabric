# Phase 3 gate review

**Decision: passed for the declared standalone profiles on 2026-09-27.**
The finite implementation, native delivery, six-language developer workflow,
guide and website requirements are complete. This decision supplies
[#240](https://github.com/KirilsTurkins/latent-service-fabric/issues/240) and
[epic #201](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) with their collective evidence.
It preserves the supported profiles and later-phase exclusions below.

The maintainer accepted all 27 guide outcomes on September 26 and authorized
subsequent corrections, promotion and publication without another approval.
The [review record](development/phase3-guide-review.md) distinguishes that
acceptance from actual command execution and later automated checks.

The [alpha.4 release](https://github.com/KirilsTurkins/latent-service-fabric/releases/tag/0.1.0-alpha.4) is published from
`2d6cc2eafc0a17dfe573be4252fa49835bebbbd6`. Exact-source CI, both complete real-VM profiles,
independent public asset authentication and all six public toolkit acquisitions
passed. The runtime tag remains immutable while engineering documentation is
synchronized separately into release.

The [complete website](https://kirilsturkins.github.io/latent-service-fabric/)
passed protected deployment and actual live browser checks, including all six
released code languages, copy, navigation, search, reloads, assets and 404 behavior.
The [publication record](development/website-publication-evidence.md) binds the
source, CI attempt, artifact and original receipts. All 26 Wiki entries have
verified maintained destinations. The Wiki and its writers were already retired;
[the cutover record](development/wiki-cutover-review.md) retains their actual
dates and final observations. #356's administrative recheck follows this decision.
Continuous documentation and performance workstreams remain open.

## Final runtime integration

The runtime release source is
`2d6cc2eafc0a17dfe573be4252fa49835bebbbd6`, promoted by
[PR #606](https://github.com/KirilsTurkins/latent-service-fabric/pull/606).
Its Git tree equals the integrated development tree containing the six SDKs,
packaged workflow, unified language selectors, SDK version updates and short
setup commands. [Exact-source CI 36275367177](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36275367177)
passed on the actual release commit.

The independently reviewed supplemental release evidence retains 38 original
JSON receipts and test logs from eight authenticated CI artifact families.
Their bytes are unchanged. The index binds each file to its original Actions
artifact ID and ZIP digest; the review records the checks and remaining limits.
The [published archive](https://github.com/KirilsTurkins/latent-service-fabric/releases/download/0.1.0-alpha.4/release-validation-0.1.0-alpha.4.zip) is
`release-validation-0.1.0-alpha.4.zip`, SHA-256
`80aa4c94db4529a5c6f43d2403e1d5bf9f51ce140fa700f2b1312087699dc0f2`.
Its actual public bytes and GitHub asset digest were independently verified.
This supplemental archive is separate from the native publisher's attested assets.

| Boundary | Verified result at the release source |
| --- | --- |
| Registered runtime correctness | 177 registered targets and 2,889 active cases. Every registered active libtest name appears in the passing workspace log; both custom harness markers, supervisor case coverage, explicit doctests and signing compatibility were checked independently. Aggregate log pass counts are not an additional population of unique cases. |
| Actual component/runtime conformance | All 19 bounded deterministic cases pass, including fresh stores, declared/platform failures, budgets, cancellation, isolation, routing, recovery and clean shutdown. Original historical completion fields and deferred evidence remain unchanged. |
| Six network clients | Rust, C, TypeScript, Go, Java and C# each pass 18 shared real-node assertions. The receipts contain 54 distinct activation identities, six operation identities, 24 physically closed held requests and six cleanly reaped nodes. Guest authoring has separate packaged qualification. |
| Security | The source-clean PR matrix passes 27 entries in 13 groups through 57 commands. Its recorded platform/threat and campaign exclusions remain explicit. |
| Providers and management | All 19 selected real S3, Vault, NATS publication and NATS trigger cases pass with owned cleanup. The separate HTTP/blob management workflow makes 31 client commands and nine activations, checks grant revocation and retained selection across two clean node shutdowns. |
| Renderer and browser boundaries | Eight renderer selections pass. Browser ingress observations retain their controlled Node SSR scope; public application component invocation is checked separately. They are not relabelled as actual Angular component rendering. |
| Actual Angular component | The protected T1 node enforces admission and isolated AOT, renders the actual Angular build, checks tenant isolation, cancellation/disconnection, compatible staged rollout, selected-deployment CAS rollback and retained native cache across restart. Both nodes shut down cleanly. Reproducibility remains `not-checked`; declared dependency coverage remains incomplete. |
| Static/CSR hosting | Exact-digest OCI transfer, two browser versions, deep-link refresh, client navigation, missing-file behavior, mounted redirects, cutover, rollback and revoked/foreign authority checks pass. All three snapshots have zero activation reservations and zero granted execution-cell leases. |
| Publication and recovery | Four independent tenant publications share one component and two package corrections. Operator and offline workflows preserve selected routing across restart and registry outage, enforce revocation, and retain an uncertain operation as `UNKNOWN`. The original operation is not automatically replayed. |
| Bounded dormant resources | The maintained 32-release/16-deployment/32-invocation profile passes with 12 OS samples and clean owned shutdown. Earlier resource campaigns retain their own measurements and environments. |

Owned OCI and renderer negative controls deliberately retain failed outcomes
after injected owner failures; the receipts and maintained validators confirm
cleanup. A successful last child stage is not confused with the owner's injected
failure. No large-scale, soak, new Harbor campaign or new full Angular-reference
campaign is claimed. Those earlier evidence sets remain separate, as do native
installed-bundle VM acceptance and public website delivery.

## Published developer tools

All 41 selected developer assets are attached to the final release. Their sizes
and SHA-256 digests match the original authenticated selection at
`cb00bf43e3f598e0f9d4bcaea2a4853d17dea8f4`. The
[packaged qualification](evidence/developer-toolkit-36262353069/README.md)
retains the real Windows/WSL2, native Windows portable, Linux, explicit SSH and
development-container execution results and their exact language/profile scope.
The standalone server archive has its separate final source above.

The [public download check](https://github.com/KirilsTurkins/latent-service-fabric/releases/download/0.1.0-alpha.4/developer-download-check-0.1.0-alpha.4.json)
executed the maintained Windows download script, authenticated the released
packages, and used the downloaded frontend to acquire each of the six toolkits
and create greeting, word-count and shipping projects: 18 projects total.
The original report is 3,765 bytes, SHA-256
`20d615d5e7395e54f9d556555aa51f4d5bb085bdbe231f0116da3759ef3a32d9`.
Its public bytes were independently verified. This supplemental observation
checks the public acquisition path; it does not claim another compilation,
node execution or WSL import. Actual runtime qualification remains in the
original packaged reports.

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
are now closed, and the maintainer has accepted the guide review. The final
native publication, runtime integration, complete-site delivery and this final
decision are recorded separately above. The historical receipts retain their
original pending fields and do not acquire a later execution identity.

## Dependency and evidence closure

| Required boundary | Verified handoff | Retained scope and qualification |
| --- | --- | --- |
| Phase 2 entry gate #158 | [Phase 2 completion](phase-2-completion.md) retains its original decision, source, failures and bounded resource profiles. | Preserve the earlier evidence population. |
| Guest contracts, providers and management #202–#221, #226/#227 | [Core/provider execution handoff](development/core-guide-validation.md), [provider workflow](testing/sdk-provider-workflow.md), and [integrated security selection](testing/phase3-security.md). | Current final integration checks must remain green. |
| Six executable clients #228/#230/#260–#263 | [Six-client guide receipts](evidence/phase3-sdk-guides-35509915448/README.md): 18 assertions per language, 54 activation identities, six operation receipts and 24 physically closed held requests. | Human guide review is separate from native transport and lifecycle qualification. |
| Publication correction #264–#267 | The [security matrix](testing/phase3-security.md) binds unchanged-component corrections, independent publications/tenants, revocation, legacy ambiguity and restart authority to exact maintained cases. All four implementation tickets are closed. | Preserve exact publication selection across every API/client and the final integration. |
| Registry policy #268–#270 and decisions #271–#274 | [OCI resource qualification](testing/phase3-resource-oci.md), the integrated security selection, and the accepted versioned registry, effects, wait-ownership, isolation and freshness decisions. These tickets are closed. | #274 remains a design handoff; it does not deliver cluster routing. |
| Runtime security #277–#281 and #238 | [Source-clean manual receipt](evidence/phase3-security-2026-09-20/manual-current.json), with [checksum](evidence/phase3-security-2026-09-20/manual-current.json.sha256): 186 libtest entries, two compiler mains and four separate-node workflows. #374 merged at `2967a9a1f069aaa476e2a294137bf7843a632a88` after all 17 checks passed; #238 is closed. | #282 is closed: [activation and monitoring evidence](development/security-baseline-evidence.md) retains the approved default-branch workflow, scheduled run `35586505063`, manual run `35752339515`, both maintained refs and the required security aggregate. |
| Resource equation #239 | [Provider recovery](testing/phase3-resource-recovery.md), [renderer memory/storage](testing/phase3-resource-renderer.md), [event and child ownership](testing/phase3-resource-events.md), and OCI qualification. #376 merged after exact-head CI passed; #239 is closed. | Keep profile-specific measurements, failed attempts and unexported counters explicit. |
| Angular application/reference #44/#236 | [Actual Angular reference workflow](testing/angular-reference-workflow.md): real signed two-build publication, public/authenticated browser delivery, DOM-reusing hydration, provider denial/cancellation, canary/revocation/restart/rollback and cleanup. #372 merged as `ffa90dc3f76f4bc589be63d313103fdb67fb5f1b`; both tickets are closed. | Preserve the restricted profile, unchecked reproducibility and declared incomplete dependency coverage. Guide review #361 is accepted and its ticket is closed. |
| Static web extension #495/#496/#497 | [Contract PR #498](https://github.com/KirilsTurkins/latent-service-fabric/pull/498), [delivery PR #501](https://github.com/KirilsTurkins/latent-service-fabric/pull/501) and [CSR/static-generator workflow PR #502](https://github.com/KirilsTurkins/latent-service-fabric/pull/502) are merged; all three tickets are closed. #502 merged as `e4c9120b7d4c14220a4315bfd8e717505e37a5b4` after [CI run 35784029574](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35784029574) passed, including the actual OCI/browser qualification. | Preserve the final integrated static and SSR checks; human guide review remains separate. |
| Native distribution #308 | [Verified native release](development/native-release-gate.md), exact-source CI and protected publisher 36278662081 passed. Both real VM profiles have complete acceptance and no gaps; public assets and attestations were independently verified. | Installation and README entry points are live. The runtime tag stays immutable; historical rehearsals keep their original sources and archives. |
| Runbooks and guides #237/#357/#358/#359/#361 | The first-node, delivery, provider, six-client and Angular walkthroughs retain their original execution receipts. All guide children and the runbook umbrella are closed. | The maintainer accepted all 27 outcomes and delegated corrections. Final native acceptance, public toolkit downloads, short setup commands and complete-site publication are verified separately. |
| Six guest SDKs #544–#549 and developer workflow #559 | All tickets are closed. The [selected toolkit](evidence/developer-toolkit-36262353069/README.md) passed complete five-entry packaged qualification at `cb00bf43e3f598e0f9d4bcaea2a4853d17dea8f4`; separate native tutorial comparisons retain 18 applications and 72 cases per platform. All 41 public developer assets match the authenticated selection. | Preserve the actual platform/language scope and original toolkit identities. The public acquisition check creates 18 projects; native server qualification remains separate. |
| Finite documentation gate #345 | Foundation, accessible theme, refreshed maintained diagrams, language selectors, frozen release versions, discovery, all 27 guide outcomes and protected complete-site publication are delivered. The gate is closed. | [Live browser and publication evidence](development/website-publication-evidence.md) and [all mapped destinations](development/wiki-cutover-review.md) pass. #356 retains the final administrative recheck after this collective decision; ongoing documentation work remains open. |

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

The promoted runtime and selected toolkits retain their independent exact-source
qualification above. The complete site passes its own successful push CI,
protected publication and browser checks; a documentation-only commit is not
represented as another native runtime execution.

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

All required guide/runbook, native distribution and finite documentation criteria
are complete. Obsolete capability/audit/policy compatibility and active legacy
Wiki navigation are removed. Historical sources, frozen snapshots, measurements,
failed attempts and original execution receipts remain unchanged.

The versioned alpha.4 documentation binds runtime source
`2d6cc2eafc0a17dfe573be4252fa49835bebbbd6` to documentation/example source
`403ded53bf00a973f77e089786cef970ab7d5bfd`, snapshot identity
`0467a564d8dc7c9ae697cd0fbcffeb052485b3f3d1f6c905b15c56e377a05197`.
It contains 227 documents, 13 example groups and seven illustrations. All 88
alpha.3 snapshot files preserve their original bytes.

After this decision is merged and published, close #240 and #201, recheck the
already disabled Wiki and retired writers, then close #356 and the finite
Phase 3 milestone. This administrative order does not change the earlier dates
when source publishing was removed and the Wiki was disabled.

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
developer qualification reports. All six authoring workflows are complete.
The collective decision above combines their evidence with the accepted guide
review, promoted runtime and actual public delivery.

## Later-phase exclusions

Phase 3 capability effects are immediate external operations, not a
transactional outbox or universal exactly-once execution. Durable guest state,
transactional workflows, distributed placement and cluster routing remain
later phases. Optional isolated native compilation does not provide guest
process containment or certify hostile multitenancy. The supported Angular
recipe does not host arbitrary Node/Express servers or unrestricted Angular
CLI projects. Each security/profile document retains those boundaries.
