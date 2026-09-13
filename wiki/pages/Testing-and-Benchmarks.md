<!-- LSF-WIKI-MANAGED -->
# Testing and benchmarks

Ordinary source/contracts/SDK checks, deterministic runtime conformance and full measurements establish different claims. Smoke success does not substitute for scale/soak evidence; a historical replay receipt is not a fresh full workload run.

| Evidence | Scope |
| --- | --- |
| Build/contract/SDK CI | Pinned Rust/MSRV, repository contracts, components and six SDK interface fixtures. |
| Contracts-job outcome matrix | Finite executable outcome/recovery checks reusing the job's checked echo and containment fixtures. |
| Manual Phase 0 baseline smoke | Deterministic baseline collection followed by the same outcome/recovery matrix; separate from full historical authorization. |
| Phase 1 conformance | Selected scheduling, ownership, isolation and failure scenarios. |
| Original full campaign | Four scales through 100k, three mixed soaks and seven benchmark runs with exact binaries. |
| Historical/current pairs | Seven controlled pairs with productionization overhead retained. |
| Extension | Per-change results, actual Docker/Kubernetes, failed attempts and original raw identities. |
| Phase 2 focused checks | Exact schemas/signatures/receipts, currentness, CAS/replay, cancellation ownership, sandbox enforcement and finite recovery. |
| Phase 2 real workflow | Separate CLI/node processes, TLS registry, package/evidence verification, invocation, promotion/rollback and restart. |

Fixed topology at 100k does not imply constant metadata RSS. Finite reclamation/plateau evidence does not prove arbitrary-duration leak freedom. Regressions and unavailable attributions remain visible.

Heavy 100k, long soak or fresh native-Linux Phase 0 work is opt-in and manual. Use bounded commands from [VALIDATION](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md) and [conformance guidance](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/phase-1-conformance.md). Documentation validation needs no new load campaign.

The [current CI contracts job](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/.github/workflows/ci.yml) runs `tools/validate_contracts.sh` and then `bash tools/run_phase0_outcome_matrix.sh`. That matrix executes the ignored `latentd` outcome/recovery cases without a second fixture build or baseline collection. The separate [Phase 0 runtime regression workflow](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/.github/workflows/phase0-regression.yml) is manual-only and retains the baseline-plus-matrix schedule. A contracts check therefore covers those runtime outcomes; it does not claim a newly measured full Phase 0 baseline.

The [retention policy](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/benchmark-retention.md) caps current data, preserves reports/provenance and records exact restoration commands. Docker raw parts were compacted; Kubernetes replay requires restoring only that original dependency. See [performance and infrastructure](Performance-and-Infrastructure).

Authorities: [measurements](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/phase-1-measurements.md), [functional completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-completion.md), [extension report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-extension-completion.md).

## Phase 2 validation scope

The maintained [operator workflow runner](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/tools/run_phase2_operator_workflow.py) exercises real build/inspect/push/pull/verify commands, authenticated publication, stale preconditions, operation lookup, bounded audit pagination, invocation, zero-data rejection, observed canary promotion, rollback, restart and revocation. It uses small temporary fixtures and explicit owned process/registry cleanup.

Successful invocation counts and candidate/baseline attribution come from actual selected revisions. A zero candidate denominator or incomplete window fails the scenario; it does not fabricate healthy evidence. Focused native compiler tests likewise exercise malformed protocol, inherited descriptors, cancellation, deadline and real child reaping under the supported unprivileged sandbox.

The [Phase 2 completion report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md) records the gate decision and links exact source, binary, policy, configuration, collector and cleanup receipts. Its resource experiment covers **32 distinct signed releases, 16 deployments and exactly two warmed portable runtime images**. The other 30 releases remain unprepared. It records 32 successful Invokes and 12 OS samples; those two images are portable preparations, not persistent native-cache hits. This does not establish constant RSS, 100k Phase 2 scale, an arbitrary-duration leak bound or a latency/throughput SLO.

The separate complete operator run passed 114 CLI processes and 18 Invokes. An earlier attempt failed at CLI call 58 with public `Unavailable` during the positive-canary schedule. Its internal cause remains **unclassified**: no distinguishing internal reason was retained. It is not a passing workflow, a resolved defect or proof of expected clock maintenance. The [attempt ledger](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/benchmarks/phase2/2026-09-13/attempts.json) preserves both outcomes; no failed Invoke was retried or removed from a denominator. [Follow-up #244](https://github.com/KirilsTurkins/latent-service-fabric/issues/244) tracks the diagnostic ambiguity. A separate pass does not establish zero-error availability.

The offline schedule separately stops the owned registry: a new pull fails while the admitted local route still succeeds, then local revocation denies invocation. Policy expiry, proof-age expiry and publisher revocation through native execution have their own focused evidence. Gate completion, release publication and live Wiki publication retain separate identities.
