# Phase 0 hot-path profiling evidence

**Status:** pass. This is optimization evidence, not a production SLO, cross-platform claim, or capacity commitment.

## Profile coverage

| Workload | Distinct scenario boundary | CPU profile | Allocation evidence | Full-invariant proof | Allocation calls | Payload in/out bytes |
| --- | --- | --- | --- | --- | ---: | ---: |
| cold-preparation | capsule validation, engine construction, and first prepared-component creation only | `profiles/cold-preparation/perf/perf-report.txt` | `profiles/cold-preparation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54454 | 0/0 |
| prepared-cache-reuse | one cold prepared component followed by one same-key bounded-cache reuse probe; no activation, failure sequence, pool probe, or throughput | `profiles/prepared-cache-reuse/perf/perf-report.txt` | `profiles/prepared-cache-reuse/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54524 | 0/0 |
| first-activation | one first echo after preparation; no warm loop, mixed failures, pool probe, or throughput | `profiles/first-activation/perf/perf-report.txt` | `profiles/first-activation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54965 | 26/26 |
| warm-execution | repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput | `profiles/warm-execution/perf/perf-report.txt` | `profiles/warm-execution/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 483585 | 25000/25000 |
| failure-containment | trap, timeout, cancellation, and memory-pressure failures with immediate cause-specific recovery | `profiles/failure-containment/perf/perf-report.txt` | `profiles/failure-containment/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 73416 | 892/664 |
| cleanup | successful activations followed by per-activation resource reclamation, cell disposition, and explicit prepared release | `profiles/cleanup/perf/perf-report.txt` | `profiles/cleanup/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 110279 | 3584/3584 |
| at-capacity-contention | real at-capacity activation batches only; no bounded-queue batch, pool microprobe, or mixed failure sequence | `profiles/at-capacity-contention/perf/perf-report.txt` | `profiles/at-capacity-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 87624 | 5164/2572 |
| queued-contention | real bounded-queue saturation batches only; no at-capacity batch, pool microprobe, or mixed failure sequence | `profiles/queued-contention/perf/perf-report.txt` | `profiles/queued-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 138515 | 19236/11460 |

Each `perf` and Heaptrack process invokes one named real-composition path only. The retained full-invariant proof is a separate unprofiled full baseline and is the sole source for the canonical topology, containment, recovery, cleanup, and reclamation assertion. The aggregate rejects a missing targeted workload, duplicate semantics, a missing proof, or a command that omits `--profile-workload`.

## Quantified contributors by workload

### cold-preparation

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | not observed at profiler resolution | — | — | — | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | not observed at profiler resolution | — | — | — | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | 5.840 | 4 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 22 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 50.510 | 207.910 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 49.400 | 644.210 | 12152 | 2553885 |

Folded totals: CPU self 99.910% and inclusive 857.960%, allocation calls 54454, allocation peak bytes 4341312; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### prepared-cache-reuse

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | not observed at profiler resolution | — | — | — | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | not observed at profiler resolution | — | — | — | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 22 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 77.030 | 315.780 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 22.800 | 373.180 | 12222 | 2553893 |

Folded totals: CPU self 99.830% and inclusive 688.960%, allocation calls 54524, allocation peak bytes 4341320; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### first-activation

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 4.860 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 18 | — |
| host context and log calls | observed at profiler resolution | — | — | 1 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 2 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 9 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 30 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 49.170 | 199.280 | 42276 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 50.460 | 763.940 | 12625 | 2553885 |

Folded totals: CPU self 99.630% and inclusive 968.080%, allocation calls 54965, allocation peak bytes 4341312; process-exit Heaptrack residue `2.82K`. Payload flow is 26 bytes submitted and 26 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### warm-execution

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.170 | 4 | — |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 18000 | — |
| host context and log calls | observed at profiler resolution | — | — | 1000 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 2000 | 32000 |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4005 | — |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.110 | 0.110 | 8022 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 1 | 4.180 | 46272 | 384 |
| unmatched_or_unknown | observed at profiler resolution | 86.080 | 1203.460 | 404282 | 10596043 |

Folded totals: CPU self 87.190% and inclusive 1207.920%, allocation calls 483585, allocation peak bytes 10628427; process-exit Heaptrack residue `2.82K`. Payload flow is 25000 bytes submitted and 25000 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### failure-containment

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.990 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 788 | — |
| host context and log calls | observed at profiler resolution | — | — | 28 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 92 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 185 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.340 | 0.340 | 326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 13.490 | 27.320 | 42448 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 86 | 537.350 | 29545 | 2553891 |

Folded totals: CPU self 99.830% and inclusive 566%, allocation calls 73416, allocation peak bytes 4341318; process-exit Heaptrack residue `2.82K`. Payload flow is 892 bytes submitted and 664 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### cleanup

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 2304 | — |
| host context and log calls | observed at profiler resolution | 0.330 | 0.330 | 128 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 256 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | 0.580 | 517 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.330 | 0.330 | 1046 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 12.410 | 29 | 42784 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 86.980 | 1027.580 | 63240 | 2553867 |

Folded totals: CPU self 100.050% and inclusive 1057.820%, allocation calls 110279, allocation peak bytes 4341294; process-exit Heaptrack residue `2.82K`. Payload flow is 3584 bytes submitted and 3584 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### at-capacity-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.830 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 1728 | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 192 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 6.970 | 7.450 | 847 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.240 | 0.240 | 790 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 9.520 | 33.810 | 42656 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 83.220 | 665.720 | 41407 | 2553897 |

Folded totals: CPU self 99.950% and inclusive 708.050%, allocation calls 87624, allocation peak bytes 4341324; process-exit Heaptrack residue `2.82K`. Payload flow is 5164 bytes submitted and 2572 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### queued-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | 0.500 | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 5184 | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 576 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 6.820 | 7.100 | 2108 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.150 | 0.150 | 2326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 6.430 | 16.960 | 43424 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 86.400 | 437.180 | 84893 | 2553887 |

Folded totals: CPU self 99.800% and inclusive 461.890%, allocation calls 138515, allocation peak bytes 4341314; process-exit Heaptrack residue `2.82K`. Payload flow is 19236 bytes submitted and 11460 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

## Experiment matrix

| Candidate | Runs | Prep us | Warm P50 us | At-cap/s | Queued/s | Fixed RSS | Prep Δ RSS | Peak RSS | Fixed VM | Prep Δ VM | Peak VM | Post-release Δ RSS / VM | Peak threads / sockets | Cache control | Topology / containment | #38 result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| worker-cell-1w-1c | 3 | 51092 | 194 | 326.424 | 613.861 | 5337088 | 13488128 | 19509248 | 89878528 | 73474048 | 163885056 | 14065664 / 73895936 | 3 / 0/0 | cache_hit; second=961 | 1w/1c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-2w-2c | 3 | 52837 | 197 | 618.820 | 653.957 | 5439488 | 13676544 | 19718144 | 159100928 | 73478144 | 233377792 | 14143488 / 74166272 | 4 / 0/0 | cache_hit; second=971 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-2w-4c | 3 | 56000 | 190 | 907.158 | 1096.191 | 5513216 | 13688832 | 19898368 | 159100928 | 73474048 | 233373696 | 14274560 / 74162176 | 4 / 0/0 | cache_hit; second=960 | 2w/4c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| worker-cell-4w-2c | 3 | 52313 | 194 | 625.635 | 1025.166 | 5361664 | 13651968 | 19759104 | 297545728 | 73482240 | 372359168 | 14286848 / 74702848 | 6 / 0/0 | cache_hit; second=963 | 4w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| on-demand-cow-disabled | 3 | 51403 | 180 | 634.912 | 1030.493 | 5423104 | 13647872 | 19648512 | 159100928 | 73469952 | 233369600 | 14127104 / 74162176 | 4 / 0/0 | cache_hit; second=956 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| pooling-cow-disabled | 3 | 56650 | 105 | 648.456 | 1083.644 | 5459968 | 14491648 | 20500480 | 159100928 | 213602304 | 373501952 | 14925824 / 214278144 | 4 / 0/0 | cache_hit; second=958 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| pooling-cow-enabled | 3 | 56989 | 97 | 660.738 | 1088.616 | 5382144 | 14032896 | 20099072 | 159100928 | 213110784 | 373010432 | 14553088 / 213782528 | 4 / 0/0 | cache_hit; second=959 | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |
| prepared-cache-disabled | 3 | 49271 | 162 | 591.250 | 1017.646 | 5427200 | 13733888 | 19681280 | 159100928 | 73474048 | 233373696 | 14143488 / 74162176 | 4 / 0/0 | disabled_cold_control; second=n/a | 2w/2c; hard invariants pass | inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive, inconclusive |

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
