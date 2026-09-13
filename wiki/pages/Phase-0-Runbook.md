<!-- LSF-WIKI-MANAGED -->
# Phase 0 historical runbook

The spike remains for isolated regression and evidence inspection. For current product usage follow [Getting started](Getting-Started).

| Purpose | Historical command |
| --- | --- |
| Finite local feasibility path | `make phase0-spike-demo` |
| Explicit deterministic authorization-check smoke | `make phase0-gate-smoke` |
| Full identity-bound authorization gate | `make phase0-gate` |

The full gate needs compatible evidence, execution identity and fresh baseline checks. A later source tree can legitimately fail its historical identity gate; never edit evidence or reinterpret smoke success as authorization. The August 30 receipt authorizes its recorded path.

Current pull-request CI keeps the executable outcome/recovery matrix in the contracts job. After `tools/validate_contracts.sh` builds the echo and containment fixtures, `bash tools/run_phase0_outcome_matrix.sh` runs the ignored `latentd` executable tests against those same files. The helper fails if a required fixture is absent; it does not silently build replacements or run the baseline collector.

The separate [Phase 0 runtime regression workflow](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/.github/workflows/phase0-regression.yml) now runs only by manual dispatch. It retains the baseline smoke collector followed by the outcome/recovery matrix. The [current CI workflow](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/.github/workflows/ci.yml) and [matrix helper](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/tools/run_phase0_outcome_matrix.sh) define current execution; the commands above retain their historical gate semantics.

New calibration/profiling/soak reference evidence requires clean native Linux host/VM conditions under the original scripts. WSL/container development and later container benchmarks do not replace that native reference contract. Heavy work is explicit and manual.

Optimization raw packages were compacted after Phase 1; the native Phase 0 raw archives remain retained. Read exact restoration instructions before replay; do not restore every archive by default.

Authorities: [completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-completion.md), [validation](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md), [retention](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/benchmark-retention.md).

For current Phase 2 package, trust and operator checks, use [Testing and benchmarks](Testing-and-Benchmarks). Phase 2 completion does not reinterpret this historical authorization procedure.
