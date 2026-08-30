# Phase 0 hot-path profiling evidence

**Status:** pass. This is optimization evidence, not a production SLO, cross-platform claim, or capacity commitment.

## Profile coverage

| Workload | Distinct scenario boundary | CPU profile | Allocation evidence | Full-invariant proof | Allocation calls | Payload in/out bytes |
| --- | --- | --- | --- | --- | ---: | ---: |
| cold-preparation | capsule validation, engine construction, and first prepared-component creation only | `profiles/cold-preparation/perf/perf-report.txt` | `profiles/cold-preparation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54864 | 0/0 |
| prepared-cache-reuse | one cold prepared component followed by one same-key bounded-cache reuse probe; no activation, failure sequence, pool probe, or throughput | `profiles/prepared-cache-reuse/perf/perf-report.txt` | `profiles/prepared-cache-reuse/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54919 | 0/0 |
| first-activation | one first echo after preparation; no warm loop, mixed failures, pool probe, or throughput | `profiles/first-activation/perf/perf-report.txt` | `profiles/first-activation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 55475 | 26/26 |
| warm-execution | repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput | `profiles/warm-execution/perf/perf-report.txt` | `profiles/warm-execution/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 565994 | 25000/25000 |
| failure-containment | trap, timeout, cancellation, and memory-pressure failures with immediate cause-specific recovery | `profiles/failure-containment/perf/perf-report.txt` | `profiles/failure-containment/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 76993 | 892/664 |
| cleanup | successful activations followed by per-activation resource reclamation, cell disposition, and explicit prepared release | `profiles/cleanup/perf/perf-report.txt` | `profiles/cleanup/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 120665 | 3584/3584 |
| at-capacity-contention | real at-capacity activation batches only; no bounded-queue batch, pool microprobe, or mixed failure sequence | `profiles/at-capacity-contention/perf/perf-report.txt` | `profiles/at-capacity-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 91811 | 5164/2572 |
| queued-contention | real bounded-queue saturation batches only; no at-capacity batch, pool microprobe, or mixed failure sequence | `profiles/queued-contention/perf/perf-report.txt` | `profiles/queued-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 142375 | 19236/11460 |

Each `perf` and Heaptrack process invokes one named real-composition path only. The retained full-invariant proof is a separate unprofiled full baseline and is the sole source for the canonical topology, containment, recovery, cleanup, and reclamation assertion. The aggregate rejects a missing targeted workload, duplicate semantics, a missing proof, or a command that omits `--profile-workload`.

## Quantified contributors by workload

### cold-preparation

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 2.480 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | not observed at profiler resolution | — | — | — | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | not observed at profiler resolution | — | — | — | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 22 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 29.480 | 120.260 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 70.310 | 797.950 | 12562 | 2553759 |

Folded totals: CPU self 99.790% and inclusive 920.690%, allocation calls 54864, allocation peak bytes 4341186; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### prepared-cache-reuse

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 2.540 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | not observed at profiler resolution | — | — | — | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | not observed at profiler resolution | — | — | — | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | 1.560 | 4 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 22 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 35.530 | 128.500 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 64.170 | 863.170 | 12617 | 2553767 |

Folded totals: CPU self 99.700% and inclusive 995.770%, allocation calls 54919, allocation peak bytes 4341194; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### first-activation

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 18 | — |
| host context and log calls | observed at profiler resolution | — | — | 1 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 2 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 9 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 30 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 29.700 | 157.080 | 42276 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 70.080 | 822.660 | 13135 | 2553759 |

Folded totals: CPU self 99.780% and inclusive 979.740%, allocation calls 55475, allocation peak bytes 4341186; process-exit Heaptrack residue `2.82K`. Payload flow is 26 bytes submitted and 26 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### warm-execution

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.150 | 4 | — |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 18000 | — |
| host context and log calls | observed at profiler resolution | — | — | 1000 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 2000 | 32000 |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4005 | — |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 8022 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 0.450 | 2.870 | 46272 | 384 |
| unmatched_or_unknown | observed at profiler resolution | 86.800 | 1182.550 | 486691 | 6401591 |

Folded totals: CPU self 87.250% and inclusive 1185.570%, allocation calls 565994, allocation peak bytes 6433975; process-exit Heaptrack residue `2.82K`. Payload flow is 25000 bytes submitted and 25000 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### failure-containment

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.910 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 788 | — |
| host context and log calls | observed at profiler resolution | — | — | 28 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 92 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 185 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | 1.200 | 326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 10.650 | 43.420 | 42448 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 88.880 | 775.220 | 33122 | 2553765 |

Folded totals: CPU self 99.530% and inclusive 820.750%, allocation calls 76993, allocation peak bytes 4341192; process-exit Heaptrack residue `2.82K`. Payload flow is 892 bytes submitted and 664 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### cleanup

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 2304 | — |
| host context and log calls | observed at profiler resolution | — | — | 128 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 256 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 0.300 | 0.300 | 517 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 1046 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 7.920 | 28.610 | 42784 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 91.450 | 1050.410 | 73626 | 2553741 |

Folded totals: CPU self 99.670% and inclusive 1079.320%, allocation calls 120665, allocation peak bytes 4341168; process-exit Heaptrack residue `2.82K`. Payload flow is 3584 bytes submitted and 3584 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### at-capacity-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.710 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 1728 | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 192 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 5.230 | 5.230 | 847 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 790 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 9.760 | 29.290 | 42656 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 84.650 | 607.230 | 45594 | 2553771 |

Folded totals: CPU self 99.640% and inclusive 642.460%, allocation calls 91811, allocation peak bytes 4341198; process-exit Heaptrack residue `2.82K`. Payload flow is 5164 bytes submitted and 2572 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### queued-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.480 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 5184 | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 576 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 5.200 | 5.480 | 2108 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 2326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 5.580 | 21.320 | 43424 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 88.880 | 457.230 | 88753 | 2553761 |

Folded totals: CPU self 99.660% and inclusive 484.510%, allocation calls 142375, allocation peak bytes 4341188; process-exit Heaptrack residue `2.82K`. Payload flow is 19236 bytes submitted and 11460 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

## Experiment matrix

| Candidate | Runs | Prep us | Warm P50 us | At-cap/s | Queued/s | Fixed RSS | Prep Δ RSS | Peak RSS | Fixed VM | Prep Δ VM | Peak VM | Post-release Δ RSS / VM | Peak threads / sockets | Cache control | Topology / containment | #38 result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| worker-cell-1w-1c | 3 | 49676 | 129 | 333.486 | 626.602 | 5505024 | 13705216 | 19591168 | 89894912 | 73474048 | 163901440 | 14012416 / 73895936 | 3 / 0/0 | cache_hit; second=952 | 1w/1c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-2w-2c | 3 | 50112 | 117 | 645.369 | 1064.286 | 5394432 | 13725696 | 19685376 | 159117312 | 73478144 | 233394176 | 14176256 / 74166272 | 4 / 0/0 | cache_hit; second=958 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-2w-4c | 3 | 49344 | 129 | 907.664 | 1162.572 | 5443584 | 13746176 | 19775488 | 159117312 | 73482240 | 233398272 | 14237696 / 74170368 | 4 / 0/0 | cache_hit; second=946 | 2w/4c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-4w-2c | 3 | 49981 | 123 | 653.479 | 1042.481 | 5386240 | 13647872 | 19881984 | 297562112 | 73482240 | 372375552 | 14286848 / 74702848 | 6 / 0/0 | cache_hit; second=951 | 4w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| on-demand-cow-disabled | 3 | 49885 | 127 | 667.037 | 1080.068 | 5414912 | 13606912 | 19587072 | 159117312 | 73469952 | 233385984 | 14098432 / 74162176 | 4 / 0/0 | cache_hit; second=948 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| pooling-cow-disabled | 3 | 57069 | 96 | 665.640 | 1089.250 | 5398528 | 14147584 | 20144128 | 159117312 | 213102592 | 373018624 | 14594048 / 213778432 | 4 / 0/0 | cache_hit; second=952 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| pooling-cow-enabled | 3 | 57307 | 95 | 640.094 | 1086.333 | 5427200 | 13983744 | 20037632 | 159117312 | 213106688 | 373022720 | 14401536 / 213778432 | 4 / 0/0 | cache_hit; second=952 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| prepared-cache-disabled | 3 | 48456 | 114 | 604.961 | 1051.456 | 5419008 | 13623296 | 19619840 | 159117312 | 73478144 | 233394176 | 14098432 / 74166272 | 4 / 0/0 | disabled_cold_control; second=n/a | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |

Fixed RSS/VM is the post-runtime, pre-component baseline. Preparation and post-release deltas are measured against that same baseline; peak values scan every retained process snapshot. `Cache control` is a direct same-key second prepare when enabled, or the explicitly non-reusable disabled-cache control. Every row retains the actual throughput values and complete canonical containment/reclamation checks in `aggregate.json`.

Each candidate retains per-run command provenance and host/toolchain context in `aggregate.json`. No new runtime optimization is adopted unless it has at least 7 materially comparable independent full runs, passes every hard invariant, has stable environment/outlier evidence, and stays within documented fixed/peak-memory costs. A mismatched source, configuration, method, environment, or run count is **inconclusive**, never an inside/outside-band result.

## Decisions and Phase 1 handoff

### fixed 2-worker/2-cell on-demand configuration: retain existing default; no new adoption

It preserves the measured fixed topology and fresh-store isolation; this archive introduces no runtime behavior change. #39 runs the final 3x100k resource soak against this configuration.

### bounded preparation/cache reuse versus cold preparation: retain existing setting; no new adoption

The matrix includes a cache-disabled control and the targeted cold-preparation profile, but Only 3 matched candidate runs are retained; Phase 0 requires at least 7 comparable runs before a faster result can justify adoption. The existing bounded immutable cache is retained without claiming a new measured adoption. #9 generalizes the cache key, policy, eviction, and multi-component compatibility proof.

### worker/cell capacity ratios: carry as configurable Phase 1 experiment

The matrix measures fixed ratios without selecting a universal winner. Only 3 matched candidate runs are retained; Phase 0 requires at least 7 comparable runs before a faster result can justify adoption. #8 owns configuration, fairness, and fixed multi-class capacity policy.

### Wasmtime pooling allocator: defer

The experiment has an explicit fixed upper bound and no retained linear-memory allowance, but it changes node-fixed mapping and reset behavior. Only 3 matched candidate runs are retained; Phase 0 requires at least 7 comparable runs before a faster result can justify adoption. #9 must provide generalized pooling limits, density evidence, and a reset/isolation proof before any production choice.

### copy-on-write initialized memory: carry as configurable Phase 1 experiment

Linux support is profiled explicitly, but its parallel-memory tradeoff is workload-dependent. Only 3 matched candidate runs are retained; Phase 0 requires at least 7 comparable runs before a faster result can justify adoption. #9 owns target-aware Wasmtime policy and must retain a safe non-COW fallback.

### avoidable activation-path allocations and payload copies: defer

Heaptrack evidence and source-attribution maps identify the current boundaries, but removing copies before the Phase 1 generic value codec and lifecycle shapes exist risks changing contracts or attribution. #9 owns canonical value mapping; #11 owns activation-envelope/lifecycle ownership and cleanup.

### store/instance reuse, persistent AOT artifacts, compiler caches, snapshots, and native execution: reject

These candidates require a new reset/isolation or provenance proof and are forbidden from silently entering Phase 0. Trusted AOT supply-chain work is Phase 2; fresh stores and instances remain mandatory in #9.

## Guardrails

The final Phase 0 configuration remains: fixed node-owned workers and cells; bounded queues, caches, logs, diagnostics, and timing history; a fresh store, limiter, host state, activation context, import table, and instance for every invocation; affirmative cleanup before cell reuse; and no per-service process, thread, listener, connection, runtime instance, or persistent guest memory. Persistent AOT artifacts, provenance-sensitive compiler caches, snapshots, store/instance reuse, shared mutable guest instances, and native execution were not enabled.

The required #39 resource soak must run after this branch is merged, using its final source tree and the retained default on-demand/COW configuration. It is the long-duration reclamation proof; these finite profiles do not replace it.
