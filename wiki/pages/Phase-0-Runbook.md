<!-- LSF-WIKI-MANAGED -->
# Phase 0 historical runbook

The spike remains for isolated regression and evidence inspection. For current product usage follow [Getting started](Getting-Started).

| Purpose | Historical command |
| --- | --- |
| Finite local feasibility path | `make phase0-spike-demo` |
| CI-sized gate path | `make phase0-gate-smoke` |
| Full identity-bound authorization gate | `make phase0-gate` |

The full gate needs compatible evidence, execution identity and fresh baseline checks. A later source tree can legitimately fail its historical identity gate; never edit evidence or reinterpret smoke success as authorization. The August 30 receipt authorizes its recorded path.

New calibration/profiling/soak reference evidence requires clean native Linux host/VM conditions under the original scripts. WSL/container development and later container benchmarks do not replace that native reference contract. Heavy work is explicit and manual.

Optimization raw packages were compacted after Phase 1; the native Phase 0 raw archives remain retained. Read exact restoration instructions before replay; do not restore every archive by default.

Authorities: [completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/phase-0-completion.md), [validation](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md), [retention](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/testing/benchmark-retention.md).
