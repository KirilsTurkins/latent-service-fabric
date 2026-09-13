# Phase 0 CI layout

Phase 0 keeps routine pull-request correctness separate from baseline and evidence collection.

## Pull requests

`CI / Repository contracts` runs `tools/validate_contracts.sh`, which builds and validates the current echo and containment fixtures together with the repository contract suite. The same job then runs `tools/run_phase0_outcome_matrix.sh` against those freshly built fixtures.

The outcome matrix selects only the ignored `latentd` Phase 0 end-to-end test. It covers the executable success/failure/recovery cases without rebuilding the complete contract suite or collecting a Phase 0 baseline. Because the main CI workflow runs for every pull request, changes that previously matched the dedicated runtime-regression path list continue to receive this matrix coverage without a second checkout or cross-workflow artifact handoff.

The contract job retains its existing bounded diagnostic and capsule artifacts. The outcome matrix does not create a new historical measurement or authorization receipt.

## Manual baseline and gate workflows

`.github/workflows/phase0-regression.yml` is an explicit manual smoke workflow. It still runs the deterministic smoke baseline, then the same outcome matrix, and retains its owned smoke evidence for 14 days. Its baseline intentionally performs the mandatory clean contract validation before collecting results.

`.github/workflows/phase0-full-validation.yml` remains the manual clean-checkout Phase 0 gate. `tools/run_phase0_gate.sh` and `tools/run_phase0_baselines.sh` retain their existing mandatory validation and evidence rules; the PR deduplication does not weaken or bypass those paths.

Use the manual workflows when new baseline/gate evidence is actually required. Routine pull requests should rely on the single Repository contracts validation plus the immediately following outcome matrix.
