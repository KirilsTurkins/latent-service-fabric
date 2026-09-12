<!-- LSF-WIKI-MANAGED -->
# Performance and infrastructure comparisons

This page preserves the September 2026 Phase 1 extension evidence. Phase 2 adds functional trust, cache and control paths; these historical numbers are not a fresh measurement of that implementation. Its [completion report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md) records separate finite evidence and qualifications; see [Testing and benchmarks](Testing-and-Benchmarks) for that scope.

The extension improves selected acquisition, cold-work isolation, recovery, ownership and catalog costs. It also retains regressions. Each report has its own population, configuration and source; percentages cannot be added across campaigns.

| Original comparison | Result and limit |
| --- | --- |
| #100 warm acquisition | Echo p50/p99 0.888/1.854 to 0.579/1.366 ms; refill p99 rose 41.936 to 54.783 ms. |
| #101 cold preparation | Warm successful p99 during distinct cold work 70.824 to 1.824 ms; candidate cold completions 28/35 versus 35/35. |
| #103 budgets | Historical resident Echo at actual 2 ms budget: 2,794/2,800 useful successes, 99.7857%; zero at 1 ms. |
| #119 disconnect cleanup | Recovery follow-ups 5/30 to 30/30 without restart; not a universal cleanup deadline. |
| #107 catalog memory | Distinct 100k post-apply RSS 2.718 to 1.117 decimal GB, 58.90% lower; shared RSS fell 14.19%; all-shape/reopened/high-water targets remain unmet. |
| #108 catalog mutations | All 24 observations faster; shared 10k reopen 41.52% slower, distinct reopened RSS 18.75% higher. |
| #109 queues | Cancellation scans/shifts eliminated, selected allocations unchanged; eight-tenant settlement median 30.0755 to 42.6785 microseconds, about 42% slower. |

## Actual Docker and Kubernetes

Each full campaign completed **9,926/9,926 successful offers**, plus separate smoke runs. Native handlers had lower warm latency and higher throughput in every headline pair. LSF used less application leaf memory and started dense cohorts sooner. Single-service memory favored native.

| Campaign | D1 Echo C1 native / LSF p50 | D1 native / LSF p99 | D32 final leaf memory native / LSF |
| --- | --- | --- | --- |
| Docker | 0.370 / 0.813 ms | 0.770 / 1.695 ms | 61.098 / 14.625 MiB |
| Kubernetes | 0.356 / 0.738 ms | 0.801 / 1.458 ms | 57.711 / 14.098 MiB |

Both campaigns used Docker Desktop/WSL2 and cached images; Kubernetes used actual local kind/containerd and Service traffic. Native partitions application resources; LSF pools them and performs more runtime work. Kubernetes requested 4 CPU / 2 GiB for each arm, but native D32 actually allowed 4.16 CPUs versus LSF 4.0. Cross-platform observations were separate campaigns, not randomized platform pairs. They do not isolate orchestration cost, establish bare-metal/cloud capacity or demonstrate HA.

Warm comparisons used one-second budgets. Sub-2 ms percentiles do not qualify 99% useful completion under actual 2 ms deadlines. Historical #103 is not an integrated post-extension guarantee. CPU includes wrapper/management/idle work; RSS, leaf charge and allocation peaks differ.

Kubernetes package replay passed independently on Linux and Windows without changing bytes. Failed/incomplete attempts and cleanup receipts remain separate. Current evidence retention is bounded to 600 MiB; historical raw packages are restored only when needed from exact storage commits.

Authorities: [complete extension report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-1-extension-completion.md), [Docker comparison](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc/README.md), [Kubernetes comparison](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/benchmarks/optimization/kubernetes-comparison/2026-09-11-container-linux-8b0441f/README.md), [retention](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/testing/benchmark-retention.md).
