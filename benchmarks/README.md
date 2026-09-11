# Benchmark program

Phase 1 and its performance extension are complete. The retained evidence covers
standalone scale, mixed-workload soaks, historical/current comparisons, focused
optimizations, and actual Docker and Kubernetes application deployments.

- [Phase 1 completion](../docs/phase-1-completion.md): functional scope, 100,000
  registrations, three mixed soaks, and the original performance comparison.
- [Extension completion](../docs/phase-1-extension-completion.md): prioritized
  optimization results, regressions, and Docker/Kubernetes comparisons.
- [Optimization evidence](optimization/README.md): per-experiment populations,
  resource boundaries, protocols, and retained reports.
- [Historical Phase 0 evidence](phase0/README.md): the original executable spike
  and its separately scoped native-Linux authorization.

Results identify environment, engine/tool versions, cache state, payloads,
sample populations, and uncertainty. Native services had lower warm request
latency in the infrastructure comparisons; LSF used less application memory at
8 and 32 services. Local Docker Desktop/WSL2 measurements do not establish
production capacity. Worker-process plugin models and future state/fusion
benchmarks remain specifications where no measured report is linked.

The [retention policy](../docs/testing/benchmark-retention.md) keeps reports,
aggregates, and provenance available while retiring historical raw payloads
from the current tree. Restore original packages from their recorded Git commits
for replay; do not treat removed working-copy payloads as missing measurements.
