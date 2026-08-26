# Phase 0 baseline evidence

`raw-results.json` and `BASELINE.md` are generated from the same full-profile Linux run by:

```bash
tools/run_phase0_baselines.sh full benchmarks/phase0
```

They are checked-in observational evidence, not an SLO or universal performance claim. The issue-24 branch workflow runs the deterministic smoke profile first and, on a successful branch push, regenerates and commits the full-profile reference files.

The raw document includes:

- multiple independent cold samples plus exact trap, timeout, and post-trap recovery probes through the `latentd phase0-spike` executable path;
- parent-process launch-to-readiness timing without a fixed readiness sleep;
- warm, containment, cause-specific recovery, and cleanup distributions built through the shared Phase 0 composition API used by the executable;
- complete-runner activation throughput with coordinated raw-pool proof at capacity and under full bounded-queue saturation;
- pre-load, post-preparation, post-workload, post-release, and shutdown topology/resource observations;
- every pass/fail threshold and invariant result;
- complete issue-23 JSON results for the cold parity probe;
- environment, toolchain, target, build profile, fixture digest, sample counts, methodology, and limitations.

Do not overwrite the reference files with results from a materially different CPU, memory size, OS/kernel, Rust/Wasmtime toolchain, target, build profile, fixture digest, worker count, pool topology, budget, threshold, or sample configuration without documenting the new environment and reason.
