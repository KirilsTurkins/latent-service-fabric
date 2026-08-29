<!-- LSF-WIKI-MANAGED -->
# Testing and benchmarks

LSF treats resource, containment, and interface claims as testable evidence.
The current Phase 0 result is deliberately bounded to its measured local and
native-Linux configurations.

## Repository validation

`make validate` and `make repository-tests` cover the contract/source baseline.
The full Phase 0 gate adds real executable composition, a fresh baseline, and
independent raw-evidence verification.

| Command | Purpose | Authorization meaning |
|---|---|---|
| `make validate` | Build/lint/test/contracts/SDK baseline | No Phase 1 authorization. |
| `make phase0-spike-demo` | Local real echo and containment demonstration | No Phase 1 authorization. |
| `make phase0-gate-smoke` | Deterministic CI-sized gate path | Reports authorization separately; not enough by itself. |
| `make phase0-gate` | Full clean-checkout gate and receipt | Required for an authorized Phase 0 handoff. |

## Recorded Phase 0 evidence

The repository retains a baseline, native-Linux calibration, CPU/allocation
profile, and long-running resource soak. The gate does not trust a summary
field alone: it checks raw artifacts, archive manifests, hashes, path safety,
schemas, configuration, identities, and regenerated aggregates.

The resource soak is a single-host observational plateau for its recorded
configuration. It is not a production SLO, cross-machine comparison, or proof
of arbitrary-duration leak freedom.

Browse the retained [Phase 0 evidence directory](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/benchmarks/phase0)
alongside the [completion-gate document](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-completion.md).
Artifact names, checksums, and execution identity are part of the evidence;
do not assume that the newest-looking directory is automatically applicable.

## Evidence has a compatibility boundary

The gate compares raw evidence and regenerated aggregates with the source,
fixture, configuration, and toolchain identity that produced them. A renamed
summary, copied archive, or changed execution path cannot turn old evidence
into a result for a newer implementation.

## Native-Linux boundary

New calibration, `perf`/Heaptrack profiling, and soak evidence must be
collected on a clean native Linux host or VM. WSL and containers are rejected
as new reference environments. The commands are manual/heavyweight and not
ordinary PR smoke checks.

## Future proof obligations

Later phases must separately prove dormant-service scaling, multi-tenant
isolation, routing, capability reclamation, state/effect recovery,
local/remote semantic equivalence, cluster behavior, and production telemetry.
The Phase 0 echo fixture cannot establish those claims by implication.

Read [Phase 0 status](Phase-0-Status), [test invariants](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/invariants.md),
and [Phase 0 baselines](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-baselines.md).
