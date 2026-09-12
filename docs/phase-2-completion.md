# Phase 2 completion review

**Gate decision: PENDING — evidence review dated September 13, 2026.**

This report maps [gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158)
to implemented delivery boundaries and their evidence. It does not yet authorize
closure of [epic #139](https://github.com/KirilsTurkins/latent-service-fabric/issues/139)
or the [Phase 2 milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/4).
The finite evidence runs and Wiki verification below are complete. Final
required CI and merge review for [documentation PR #243](https://github.com/KirilsTurkins/latent-service-fabric/pull/243)
and gate #158 remain pending. The gate owner will update this decision after
those results and the final dependency ledger are reviewed.

The [Phase 1 completion](phase-1-completion.md) and
[performance extension](phase-1-extension-completion.md) retain their original
measurements, failures, source identities and qualifications. They supply
catalog, routing, execution and ownership foundations; their receipts do not
substitute for current Phase 2 evidence.

## Current gate evidence

These centrally executed results have compact retained receipts identifying
their source, binaries, configuration, collectors and fixtures. They are
separate observations; a later merge revision does not replace a measured
revision. Earlier failed and superseded attempts remain in the
[attempt ledger](../benchmarks/phase2/2026-09-13/attempts.json).

| Check | Observed result and exact scope | Retained evidence |
| --- | --- | --- |
| Real authority through native execution | **3/3 PASS, 57.03 seconds** in [trust_currentness.rs](../apps/latentd/src/standalone/start/tests/trust_currentness.rs): proof-age expiry, joint-policy expiry and publisher revocation. Each case performs one real isolated compilation and successful invocation before invalidation. | [Native currentness receipt](../benchmarks/phase2/2026-09-13/native-currentness-receipt.json), including test/source/compiler/fixture identities and the unprivileged execution profile. |
| Registry outage versus local eligibility | **PASS: 24 CLI commands and 3 Invoke attempts: 2 successes and 1 revoked-release denial**. The [offline workflow](../tools/run_phase2_offline_workflow.py) authenticates transfer before registry shutdown; a new pull fails while the admitted local route still succeeds. Local revocation then denies use with the registry still stopped. | [Offline receipt](../benchmarks/phase2/2026-09-13/offline-receipt.json), retaining transfer failure, denied Invoke, identities and actual shutdown/reap. |
| Dormant release/resource profile | **Final rerun PASS** for `phase2-dormant-32-r1`: **32 distinct signed releases, 16 deployments, exactly 2 warmed portable runtime images, 32 successful Invokes, 133 control commands and 12 OS samples**. The other 30 releases remain unprepared. The final collector/validator checks passed **35/35**. | [Resource receipt](../benchmarks/phase2/2026-09-13/resource-receipt.json), 86,476 bytes, with all samples, fixed configuration, catalog counts, clean worker joins, process reap and temporary-output removal. |
| Complete operator workflow | **PASS: 114 CLI processes and 18 successful Invokes**, including attributed canary evaluation/promotion, managed operation replay/lookup, rollback, restart and revocation. | [Operator receipt](../benchmarks/phase2/2026-09-13/operator-receipt.json), with exact identities, decisions, operation receipts and shutdown records. The preceding failed attempt remains separately classified below. |
| Selected strict lint checks | The four centrally selected packages passed Clippy with all targets/features after the test-only fixes. | [Attempt ledger](../benchmarks/phase2/2026-09-13/attempts.json) and [dependency/check ledger](../benchmarks/phase2/2026-09-13/dependencies.json). This result does not stand in for final gate CI. |
| Actual observed-build provenance | The retained contracts-job artifact identifies the actual tested merge, build inputs, component and SBOM input inventory consumed by registry integration. | [Observed-build receipt](../benchmarks/phase2/2026-09-13/observed-echo-receipt.json) and [captured files](../benchmarks/phase2/2026-09-13/observed-echo/), separate from synthetic workflow fixtures. |
| Published Wiki | **30 actual Git blobs verified: 26 pages, 4 assets and 147 links** against the managed source inventory. | [Wiki publication receipt](../benchmarks/phase2/2026-09-13/wiki-publication.json), with exact source/live revisions and successful publication run. |

The new trust tests independently renew the bounded clock lease before checking
the exact denial cause. They retain both readiness and an invocation future
created before invalidation, then deny materialization, final start and owned
and borrowed preparation. Isolated-compile, native-loader and guest-store counts
do not increase. Reopening the same native cache cannot revive the catalog's old
grant. Expired-policy and revoked-publisher catalog recovery keeps the historical
record readable with denied eligibility. A fresh catalog recovery may reverify
still-valid evidence after proof-age expiry; that documented refresh creates a
new capability and does not upgrade an old in-process token.

The resource profile uses portable preparation. Its two warmed images are not
two persistent native-cache hits. Native image mapping ownership and isolated
child cleanup have their own focused tests. See the fixed
[resource profile](testing/phase-2-resource-profile.md) and
[offline validation instructions](testing/phase-2-offline-validation.md).

## All eighteen implementation and documentation dependencies

The [dependency ledger](../benchmarks/phase2/2026-09-13/dependencies.json)
records the eighteen child issues, reviewed heads, merge revisions and required
checks. Features #140–156 are delivered; #156 merged through
[PR #242](https://github.com/KirilsTurkins/latent-service-fabric/pull/242) at
`bda3017345b0bf7d656d151cec10a5b3fd8cb165`. Documentation #157 is represented by
PR #243 in the decision review above. The map below connects each dependency
to its implementation and verification surface; source coverage alone is not
a passing execution result.

| Child | Concrete implementation | Focused tests | Operator or contract documentation |
| --- | --- | --- | --- |
| [#140 immutable package identity](https://github.com/KirilsTurkins/latent-service-fabric/issues/140) | [Package codec/model](../crates/latent-artifacts/src/package/) | [Golden bytes](../crates/latent-artifacts/tests/package_golden.rs), [adversarial format](../crates/latent-artifacts/tests/package_adversarial.rs) | [Package format](protocol/package-format.md) |
| [#141 deterministic packaging](https://github.com/KirilsTurkins/latent-service-fabric/issues/141) | [Packaging and directory inventory](../crates/latent-packaging/src/) | [Roundtrip](../crates/latent-packaging/tests/package_roundtrip.rs), [component/WIT validation](../crates/latent-packaging/tests/component_validation.rs) | [Packaging](component-development/packaging.md) |
| [#142 authenticated OCI transfer](https://github.com/KirilsTurkins/latent-service-fabric/issues/142) | [OCI HTTP adapter](../crates/latent-oci/src/http/) | [Real registry](../crates/latent-oci/tests/registry.rs), [transport bounds](../crates/latent-oci/tests/http_transport.rs) | [Registry profile](reference/oci-registry.md) |
| [#143 signatures and publisher trust](https://github.com/KirilsTurkins/latent-service-fabric/issues/143) | [Signing and current publisher verification](../crates/latent-signing/src/) | [Publisher trust](../crates/latent-signing/tests/publisher_trust.rs), [bounded trust inputs](../crates/latent-signing/tests/trust_inputs.rs) | [Publisher trust](reference/publisher-trust.md) |
| [#144 build provenance](https://github.com/KirilsTurkins/latent-service-fabric/issues/144) | [Builder verification](../crates/latent-signing/src/builder_verify.rs) | [Provenance](../crates/latent-signing/tests/build_provenance.rs), [actual observed-build registry roundtrip](../crates/latent-oci/tests/registry/provenance.rs) | [Build provenance](reference/build-provenance.md) |
| [#145 digest-bound SBOMs](https://github.com/KirilsTurkins/latent-service-fabric/issues/145) | [SBOM generation, association and policy](../crates/latent-packaging/src/sbom/) | [Association/policy](../crates/latent-packaging/tests/sbom_association.rs), [observed-build SBOM roundtrip](../crates/latent-oci/tests/registry/provenance/sbom.rs) | [SBOM contract](component-development/sbom.md) |
| [#146 verified catalog admission](https://github.com/KirilsTurkins/latent-service-fabric/issues/146) | [Supply-chain authority](../crates/latent-policy/src/supply_chain.rs), [catalog admission](../crates/latent-artifacts/src/local_repository/admission.rs) | [Real signed catalog](../crates/latent-policy/src/supply_chain/tests/catalog.rs), [historical validation](../crates/latent-policy/src/supply_chain/tests/history.rs) | [Package admission](reference/package-admission.md) |
| [#147 release compatibility](https://github.com/KirilsTurkins/latent-service-fabric/issues/147) | [Runtime requirements](../crates/latent-manifest/src/runtime_compatibility.rs), [exact package comparison](../crates/latent-packaging/src/semantics/compatibility.rs) | [Package compatibility](../crates/latent-packaging/tests/compatibility.rs), [deployment runtime checks](../crates/latent-control-store/src/deployments/tests/runtime_compatibility.rs) | [Release compatibility](reference/release-compatibility.md) |
| [#148 durable lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/issues/148) | [Lifecycle store and capabilities](../crates/latent-artifacts/src/lifecycle/) | [Real evidence renewal/revocation](../crates/latent-policy/src/supply_chain/tests/lifecycle.rs), [runtime currentness](../crates/latent-wasmtime/tests/lifecycle.rs) | [Lifecycle and recovery](reference/release-lifecycle.md) |
| [#149 bounded raw cache](https://github.com/KirilsTurkins/latent-service-fabric/issues/149) | [Raw cache](../crates/latent-artifacts/src/raw_cache/) | [Capacity, ownership and recovery](../crates/latent-artifacts/src/raw_cache/tests.rs), [OCI cache](../crates/latent-oci/tests/http_cache.rs) | [Raw cache](reference/raw-artifact-cache.md) |
| [#150 isolated trusted compiler](https://github.com/KirilsTurkins/latent-service-fabric/issues/150) | [AOT supervisor, sandbox and authenticated output](../crates/latent-wasmtime/src/aot/) | [Sandbox](../crates/latent-wasmtime/tests/aot_sandbox.rs), [supervisor ownership](../crates/latent-wasmtime/tests/aot_supervisor.rs), [exact inputs](../crates/latent-wasmtime/tests/isolated_aot.rs) | [Trusted AOT boundary](runtime/trusted-aot.md) |
| [#151 persistent native reuse](https://github.com/KirilsTurkins/latent-service-fabric/issues/151) | [Authenticated cache composition](../crates/latent-wasmtime/src/aot/cache.rs), [audited loader](../crates/latent-wasmtime/src/aot/loader.rs) | [Reopen/hit](../crates/latent-wasmtime/tests/native_aot_cache/reopen.rs), [tamper](../crates/latent-wasmtime/tests/native_aot_cache/tamper.rs), [retained images](../crates/latent-wasmtime/tests/native_aot_cache/ownership.rs) | [Native node settings](reference/standalone-node.md#optional-isolated-aot-compilation) |
| [#152 audit and bounded observations](https://github.com/KirilsTurkins/latent-service-fabric/issues/152) | [Durable journal](../crates/latent-audit/src/durable/), [wire queries/leases](../crates/latent-wire/src/management/audit/) | [Journal tests](../crates/latent-audit/src/durable/tests.rs), [node audit startup](../apps/latentd/src/standalone/start/tests/audit.rs) | [Phase 2 audit](phase-2-audit.md) |
| [#153 durable rollout coordination](https://github.com/KirilsTurkins/latent-service-fabric/issues/153) | [Shared coordinator](../crates/latent-rollout/src/coordinator.rs), [combined catalog](../crates/latent-control-store/src/deployments/) | [Atomic rollout publication](../crates/latent-control-store/src/deployments/tests/rollouts.rs), [coordinator ownership](../crates/latent-rollout/src/tests/ownership.rs) | [Rollout protocol](phase-2-rollouts.md) |
| [#154 canary promotion](https://github.com/KirilsTurkins/latent-service-fabric/issues/154) | [Sealed observation/evaluation](../crates/latent-telemetry/src/phase2_canary/), [promotion](../crates/latent-rollout/src/canary/promote.rs) | [Promotion assessment](../crates/latent-telemetry/src/phase2_canary/tests/promotion.rs), [actual node Invoke](../apps/latentd/src/standalone/start/tests/rollouts/canary.rs) | [Controlled promotion](phase-2-canary-promotion.md) |
| [#155 atomic rollback](https://github.com/KirilsTurkins/latent-service-fabric/issues/155) | [Rollback coordinator](../crates/latent-rollout/src/rollback.rs), combined catalog transaction | [Restoration and pins](../crates/latent-control-store/src/deployments/tests/rollouts/rollback.rs), [target trust](../crates/latent-control-store/src/deployments/tests/rollouts/rollback/trust.rs) | [Rollback and recovery](phase-2-rollback.md) |
| [#156 management and CLI](https://github.com/KirilsTurkins/latent-service-fabric/issues/156) | [CLI control workflows](../apps/latent/src/management/phase2/), [managed deployment RPC](../crates/latent-wire/src/management/deployment/managed.rs) | [CLI validation/projection](../apps/latent/src/management/phase2/tests.rs), [mixed managed writers](../crates/latent-control-store/src/deployments/tests/operations/mixed.rs), [real process workflow](../tools/run_phase2_operator_workflow.py) | [Operator workflows](phase-2-operator-workflows.md), [CLI reference](reference/operator-cli.md) |
| [#157 operator documentation](https://github.com/KirilsTurkins/latent-service-fabric/issues/157) | [Delivery notes](phase-2-delivery.md), [delivery diagram](assets/phase2-delivery-boundary.svg) | Link/schema/diagram checks and [verified Wiki publication](../benchmarks/phase2/2026-09-13/wiki-publication.json) | [Capsule creation](component-development/creating-a-capsule.md), [quickstart](development/standalone-quickstart.md), [topology](operations/topology.md), [validation](../VALIDATION.md) |

The #157 links name their final repository destinations, reviewed from the
separate documentation worktree. Wiki synchronization is independently
verified from source `d9778eae9d83d5738e3f70b6ba15080a24c0d63a` to live Wiki
revision `7cd26bb98c751df82b530d635f978f9934131414` by
[run 34724297039](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34724297039).
That publication describes delivered Phase 2 features, keeps gate #158 open
and labels Phase 3 as planned; it does not claim a later documentation merge.

## Acceptance-criterion reconciliation

The following ten rows follow the gate issue's acceptance criteria in order.
The retained receipts and dependency/check ledger carry execution results;
the linked source suites show the precise boundary each result exercises.

| Criterion | Implementation and test evidence | Evidence disposition |
| --- | --- | --- |
| 1. Reconcile every requirement and child | The eighteen-row map above covers package identity through runbooks. The [existing overlap rendezvous](../crates/latent-wasmtime/tests/containment_backend/rendezvous.rs) remains the owner of the #132 reliability correction. | [Dependency ledger](../benchmarks/phase2/2026-09-13/dependencies.json) and [attempt dispositions](../benchmarks/phase2/2026-09-13/attempts.json); #132 retains its own closed disposition below. |
| 2. Real registry through rollback/revoke/status | [Operator scenario](../tools/phase2_operator_scenario.py) and [canary schedule](../tools/phase2_operator_canary.py) use actual CLI/node processes, separate storage, TLS registry transfer, verified publication, managed deployment, attributed invocation, promotion, rollback, restart and revocation. | [Passing 114-process/18-Invoke receipt](../benchmarks/phase2/2026-09-13/operator-receipt.json) binds exact package/component/policy/runtime and process/build identities. The earlier failure remains separate. |
| 3. Reject invalid content before routing or preparation | [Authority](../crates/latent-policy/src/supply_chain/tests/authority.rs), [catalog](../crates/latent-policy/src/supply_chain/tests/catalog.rs), [runtime compatibility](../crates/latent-policy/src/supply_chain/tests/runtime.rs), [deployment supply chain](../crates/latent-control-store/src/deployments/tests/supply_chain.rs), [runtime admission](../crates/latent-wasmtime/tests/admission.rs), native tamper/currentness tests cover independent negative boundaries. | The [real native currentness receipt](../benchmarks/phase2/2026-09-13/native-currentness-receipt.json) adds expiry/revocation composition to the dependency suites. Negative checks do not derive authorization from positive cache state. |
| 4. Evidence, scope, bounds and offline behavior | [Signature currentness](../crates/latent-signing/tests/publisher_trust/currentness.rs), provenance/SBOM tests, [referrer bounds](../crates/latent-oci/tests/http_pull/referrers.rs), [HTTP cache ownership](../crates/latent-oci/tests/http_cache.rs), [management integration](../crates/latent-wire/tests/management_service/) and the distinct outage/currentness schedules above. | [Actual observed-build artifact](../benchmarks/phase2/2026-09-13/observed-echo-receipt.json), [offline transfer/denial evidence](../benchmarks/phase2/2026-09-13/offline-receipt.json) and dependency authentication/redaction suites. Registry availability does not determine local trust. |
| 5. Concurrency, interrupted durability and monotonic rollback | [Lifecycle cutpoints](../crates/latent-artifacts/src/lifecycle/store/tests.rs), [publication visibility](../crates/latent-artifacts/src/local_repository/visibility_tests.rs), [rollout recovery](../crates/latent-control-store/src/deployments/tests/rollouts/recovery.rs), [managed-operation persistence](../crates/latent-control-store/src/deployments/tests/operations/persistence.rs), rollback/revocation tests and mixed-writer CAS tests. | Dependency suites exercise revoke after preparation, failed post-rename synchronization, stale writers and preserved pins. The operator receipt separately retains real rollback/restart outcomes. A selected but unconfirmed publication remains uncertain. |
| 6. AOT, caches, pins and actual cleanup | Sandbox/supervisor/source tests above; native reopen/tamper/image ownership; raw-cache staging, eviction, malformed recovery and pin tests. [Native-loader source guard](../tools/native_loader_boundary.py) checks the audited unsafe boundary. | [Native receipt](../benchmarks/phase2/2026-09-13/native-currentness-receipt.json) binds compiler/runtime/host identities and no-additional-work assertions. Focused owner suites retain separate compiler/output/read/image accounting; process receipts record actual joins/reap. |
| 7. Fixed dormant/resource experiment | [Frozen profile](testing/phase-2-resource-profile.md), [runner](../tools/phase2_gate_resource.py), [OS observer](../tools/phase2_gate_resource_os.py) and [receipt validator tests](../tools/tests/test_phase2_gate_resource.py). | [Final 12-sample receipt](../benchmarks/phase2/2026-09-13/resource-receipt.json), fixed config, exact catalog counts, two-image preparation, shutdown joins and process reap; 35 collector/validator checks passed. The superseded observation is in the attempt ledger. |
| 8. Current workflows, docs, diagrams and wiki | #156 executable workflows, [management reference](reference/management-services.md), [node configuration](reference/standalone-node.md), [API surface](api-surface.md), [architecture](architecture/overview.md), #157 runbooks and delivery SVG. | [Wiki receipt](../benchmarks/phase2/2026-09-13/wiki-publication.json) verifies all 30 published blobs and 147 links against its exact source. Documentation merge/CI is covered by the gate decision above. |
| 9. CI and compact reproducible evidence | [Required CI workflow](../.github/workflows/ci.yml), [validation contract](../VALIDATION.md), focused security/restart/ownership suites and [retention policy](testing/benchmark-retention.md). | [Dependency/check ledger](../benchmarks/phase2/2026-09-13/dependencies.json), compact receipts and [failed/unavailable attempt records](../benchmarks/phase2/2026-09-13/attempts.json) preserve actual reviewed/measured identities. No final gate CI result is inferred from local success. |
| 10. Report and closure decision | This report, dependency ledger and retained evidence support the decision. | The explicit decision at the top governs closure. Later closure/merge identities do not rewrite the identities of measured executions. |

[Issue #132](https://github.com/KirilsTurkins/latent-service-fabric/issues/132),
“Make mixed memory containment overlap deterministic,” is **closed as completed**
(September 12, 2026). That disposition belongs to #132. Phase 2 neither reopens,
duplicates nor reassigns it, and does not erase the original reliability failure
when citing the corrected overlap test.

## Provenance and measurement boundaries

The operator, offline and resource exporters create fresh publisher/builder
signatures over exact package identities and regenerate their SBOM associations.
Their build observation is explicitly **synthetic test evidence**. They establish
signature production, transfer and policy/runtime composition for that fixture;
they do not prove that a production build produced the component.

The separate
[`real_observed_build_provenance_roundtrip`](../crates/latent-oci/tests/registry.rs)
consumes captured build inputs through the
[provenance integration](../crates/latent-oci/tests/registry/provenance.rs).
The CI contracts job publishes `phase-2-observed-echo-<source revision>` and the
registry job consumes it. The [retained artifact receipt](../benchmarks/phase2/2026-09-13/observed-echo-receipt.json)
binds PR #242 head `a35a58950bff187b2702164fd2f13b0fb54b237b`, actual tested merge
`c0c3d5c39acfcdc3326987805da49c17e69bfdcf`,
[workflow run 34723362373](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34723362373)
and artifact `10306997403`. It records byte lengths and SHA-256 digests for the
ten [captured files](../benchmarks/phase2/2026-09-13/observed-echo/), including
the component, observation, contracts, WIT inventory and SBOM inputs. These
are historical CI execution identities, not the later merge or gate head.
The maintained observed build is nonhermetic, as documented in
[build provenance](reference/build-provenance.md).

The dormant experiment measures one fixed single-node population. Thirty of its
32 releases remain unprepared; 16 deployments reference only the two warmed
components. It reports OS observations separately from logical retained
metadata, prepared images and invocation ownership. Reclamation means that the
declared transient owners retire and shutdown actually completes. It does not
require RSS to return to baseline or delete authoritative release/audit history.
No result here establishes 100k Phase 2 scale, an arbitrary-duration leak bound,
a latency/throughput SLO or production cluster capacity.

## Retained failure and availability qualification

The preceding operator attempt is **FAILED, with an unclassified internal
cause**. CLI call 58 returned public `Unavailable` during the positive-canary
schedule; no gRPC error code or distinguishing internal reason was retained.
It did not establish a passing canary or a passing workflow. The
[attempt ledger](../benchmarks/phase2/2026-09-13/attempts.json) retains that
outcome and records completed owned cleanup. Compact retention does not make
the missing internal diagnostic recoverable.

Source inspection found no additional RPC or retained Rust owner introduced
by the Python result collector. It also identified multiple fail-closed paths
that can surface public `Unavailable`; the public result cannot establish
which path ran. In particular, it does **not** establish that periodic clock
lease maintenance caused this failure. The separate passing run used the same
production binaries, maintained collector code, fixed bounds and logical
workload with fresh signed fixtures. No failed Invoke was retried, removed
from a denominator or converted into success; no resource limit was raised
and no production fix explains the later pass.

Current policy/clock readiness and finite resource availability remain
conditions of use. A retained grant or cache hit cannot bypass them, and
nonblocking admission can deny a start when currentness cannot be established.
The observed pass therefore provides finite workflow evidence, **not a
zero-error availability or SLO guarantee**. The failed attempt is not dismissed
as expected maintenance or classified as a resolved defect.

[Follow-up #244](https://github.com/KirilsTurkins/latent-service-fabric/issues/244)
tracks the independently confirmed diagnostic ambiguity between
`TryLockError::WouldBlock` and `TryLockError::Poisoned`. Both remain fail-closed;
distinguishing their diagnostics neither attributes nor fixes the historical
operator failure. The follow-up has no Phase 2 milestone and is not an
additional required Phase 2 feature.

## Migration, security and finite limits

- Package digest, component digest, publisher/builder proof, runtime profile
  and lifecycle permission remain distinct. Copying bytes, a diagnostic verify
  report or a cache hit cannot authorize execution. Currentness is checked on
  retained work as well as new preparation.
- Catalog formats 1–4 preserve their documented decode and absent-field rules.
  Managed operations add global state-version CAS alongside object generation.
  Finite receipt lookup returns unknown for absent or evicted history; unknown
  does not prove an operation never ran. Retained replay never reapplies a
  mutation or renews a grant. See [operator recovery](phase-2-operator-workflows.md).
- Canary promotion requires the exact bound cohort, policy and completed,
  quiescent observation window. No data, incomplete capture and unavailable
  evidence cannot be promoted as healthy. Rollback restores the captured
  eligible target through a new monotonic generation; legacy plans without a
  captured target cannot synthesize one. See [promotion](phase-2-canary-promotion.md)
  and [rollback](phase-2-rollback.md).
- Verified but ineligible desired rows recover as denying history so operators
  can inspect/remove/update them. Corruption still prevents authoritative
  recovery. Explicit fresh compilation, including startup recovery, may acquire
  current grants; retained in-process tokens never upgrade automatically.
- Raw/native caches are replaceable and bounded independently of authoritative
  catalogs. Native reuse is opt-in on the documented Linux x86_64 sandbox
  profile, with an approved compiler and protected local authentication key.
  Native blob/receipt replacement cannot forge that key's authorization;
  trusted host administration and key protection remain part of the boundary.
  Page-rounded image charges are not total Wasmtime heap, COW storage or RSS.
- Audit is finite, with explicit loss, outcome uncertainty and prior-session
  coverage limits. Catalog durability and audit acknowledgement are separate.
  Cancellation of a caller does not cancel already-owned disk work or prove a
  child has exited. Shutdown records actual joins/reap and reports late or
  incomplete cleanup as failure.
- The standalone management listener remains authenticated loopback gRPC.
  Registry TLS does not provide remote node transport security. Browser/SSR
  packages are artifact contracts only. General HTTP/blob/secrets/events/service
  providers and application ingress/Angular execution belong to Phase 3; state,
  effects, cluster operation and durable workflows remain later phases.

## Retained evidence inventory

The compact evidence directory is
[`benchmarks/phase2/2026-09-13/`](../benchmarks/phase2/2026-09-13/):

| Artifact | Scope |
| --- | --- |
| [operator-receipt.json](../benchmarks/phase2/2026-09-13/operator-receipt.json) | Exact build/package/policy/configuration identities, 114 CLI processes, 18 successful Invokes, control/canary/rollback/revocation records and both node shutdowns. |
| [offline-receipt.json](../benchmarks/phase2/2026-09-13/offline-receipt.json) | Authenticated transfer, owned registry stop, failed new transfer, successful local use, local revocation denial and process cleanup. |
| [resource-receipt.json](../benchmarks/phase2/2026-09-13/resource-receipt.json) | Fixed profile/configuration, all 12 OS/inventory samples, exact catalog population and invocation identities, compiler/cleanup/audit/coordinator joins and process reap. |
| [native-currentness-receipt.json](../benchmarks/phase2/2026-09-13/native-currentness-receipt.json) | Three real-authority native tests, exact test/source/compiler/fixture/host identities and bounded compile/load scope. |
| [dependencies.json](../benchmarks/phase2/2026-09-13/dependencies.json) | Child dispositions, reviewed heads, merge revisions and required CI/check identities. |
| [wiki-publication.json](../benchmarks/phase2/2026-09-13/wiki-publication.json) | Actual source/live Wiki revisions, publication run, source manifest digest and verified published blob/link counts. |
| [attempts.json](../benchmarks/phase2/2026-09-13/attempts.json) | Failed, unavailable, superseded and final passing attempts, with explicit diagnostic and retention limits. |
| [observed-echo-receipt.json](../benchmarks/phase2/2026-09-13/observed-echo-receipt.json) and [observed-echo/](../benchmarks/phase2/2026-09-13/observed-echo/) | Actual CI artifact identity and ten captured build/component/WIT/SBOM files with per-file lengths and SHA-256 digests. |

These receipts preserve execution identities and qualifications independently
of the completion decision. The gate owner records final CI/merge review and
closure through the decision at the top; no local pass substitutes for that
review.
