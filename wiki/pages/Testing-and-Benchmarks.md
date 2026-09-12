<!-- LSF-WIKI-MANAGED -->
# Testing and benchmarks

Ordinary source/contracts/SDK checks, deterministic runtime conformance and full measurements establish different claims. Smoke success does not substitute for scale/soak evidence; a historical replay receipt is not a fresh full workload run.

| Evidence | Scope |
| --- | --- |
| Build/contract/SDK CI | Pinned Rust/MSRV, repository contracts, components and six SDK interface fixtures. |
| Runtime smoke | Finite real executable/invariant checks. |
| Phase 1 conformance | Selected scheduling, ownership, isolation and failure scenarios. |
| Original full campaign | Four scales through 100k, three mixed soaks and seven benchmark runs with exact binaries. |
| Historical/current pairs | Seven controlled pairs with productionization overhead retained. |
| Extension | Per-change results, actual Docker/Kubernetes, failed attempts and original raw identities. |
| Phase 2 focused checks | Exact schemas/signatures/receipts, currentness, CAS/replay, cancellation ownership, sandbox enforcement and finite recovery. |
| Phase 2 real workflow | Separate CLI/node processes, TLS registry, package/evidence verification, invocation, promotion/rollback and restart. |

Fixed topology at 100k does not imply constant metadata RSS. Finite reclamation/plateau evidence does not prove arbitrary-duration leak freedom. Regressions and unavailable attributions remain visible.

Heavy 100k, long soak or fresh native-Linux Phase 0 work is opt-in and manual. Use bounded commands from [VALIDATION](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md) and [conformance guidance](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/phase-1-conformance.md). Documentation validation needs no new load campaign.

The [retention policy](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/benchmark-retention.md) caps current data, preserves reports/provenance and records exact restoration commands. Docker raw parts were compacted; Kubernetes replay requires restoring only that original dependency. See [performance and infrastructure](Performance-and-Infrastructure).

Authorities: [measurements](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/phase-1-measurements.md), [functional completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-completion.md), [extension report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-extension-completion.md).

## Phase 2 validation scope

The maintained [operator workflow runner](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/tools/run_phase2_operator_workflow.py) exercises real build/inspect/push/pull/verify commands, authenticated publication, stale preconditions, operation lookup, bounded audit pagination, invocation, zero-data rejection, observed canary promotion, rollback, restart and revocation. It uses small temporary fixtures and explicit owned process/registry cleanup.

Successful invocation counts and candidate/baseline attribution come from actual selected revisions. A zero candidate denominator or incomplete window fails the scenario; it does not fabricate healthy evidence. Focused native compiler tests likewise exercise malformed protocol, inherited descriptors, cancellation, deadline and real child reaping under the supported unprivileged sandbox.

These checks establish concrete behavior, not a new throughput/RSS SLO or a full 100k campaign. [Gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158) remains pending; gate evidence and release/Wiki publication identities must be recorded separately.
