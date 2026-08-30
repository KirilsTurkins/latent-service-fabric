# Phase 0 hot-path profiling evidence

**Status:** pass. This is optimization evidence, not a production SLO, cross-platform claim, or capacity commitment.

## Profile coverage

| Workload | Distinct scenario boundary | CPU profile | Allocation evidence | Full-invariant proof | Allocation calls | Payload in/out bytes |
| --- | --- | --- | --- | --- | ---: | ---: |
| cold-preparation | capsule validation, engine construction, and first prepared-component creation only | `profiles/cold-preparation/perf/perf-report.txt` | `profiles/cold-preparation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 54943 | 0/0 |
| prepared-cache-reuse | one cold prepared component followed by one same-key bounded-cache reuse probe; no activation, failure sequence, pool probe, or throughput | `profiles/prepared-cache-reuse/perf/perf-report.txt` | `profiles/prepared-cache-reuse/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 55028 | 0/0 |
| first-activation | one first echo after preparation; no warm loop, mixed failures, pool probe, or throughput | `profiles/first-activation/perf/perf-report.txt` | `profiles/first-activation/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 55676 | 26/26 |
| warm-execution | repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput | `profiles/warm-execution/perf/perf-report.txt` | `profiles/warm-execution/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 662327 | 25000/25000 |
| failure-containment | trap, timeout, cancellation, and memory-pressure failures with immediate cause-specific recovery | `profiles/failure-containment/perf/perf-report.txt` | `profiles/failure-containment/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 82119 | 892/664 |
| cleanup | successful activations followed by per-activation resource reclamation, cell disposition, and explicit prepared release | `profiles/cleanup/perf/perf-report.txt` | `profiles/cleanup/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 140936 | 3584/3584 |
| at-capacity-contention | real at-capacity activation batches only; no bounded-queue batch, pool microprobe, or mixed failure sequence | `profiles/at-capacity-contention/perf/perf-report.txt` | `profiles/at-capacity-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 99982 | 5164/2572 |
| queued-contention | real bounded-queue saturation batches only; no at-capacity batch, pool microprobe, or mixed failure sequence | `profiles/queued-contention/perf/perf-report.txt` | `profiles/queued-contention/allocation/heaptrack-report.txt` | `full-invariant-proof/raw-results.json` | 149592 | 19236/11460 |

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
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 22 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 18.100 | 20.550 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 81.660 | 624.360 | 12641 | 818468 |

Folded totals: CPU self 99.760% and inclusive 644.910%, allocation calls 54943, allocation peak bytes 2605895; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

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
| Wasmtime engine and component preparation | observed at profiler resolution | 16 | 37.220 | 42272 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 83.680 | 663.820 | 12726 | 818476 |

Folded totals: CPU self 99.680% and inclusive 701.040%, allocation calls 55028, allocation peak bytes 2605903; process-exit Heaptrack residue `2.82K`. Payload flow is 0 bytes submitted and 0 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

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
| Wasmtime engine and component preparation | observed at profiler resolution | 19.750 | 78.450 | 42276 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 79.930 | 598.330 | 13336 | 818468 |

Folded totals: CPU self 99.680% and inclusive 676.780%, allocation calls 55676, allocation peak bytes 2605895; process-exit Heaptrack residue `2.82K`. Payload flow is 26 bytes submitted and 26 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### warm-execution

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | — |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 18000 | — |
| host context and log calls | observed at profiler resolution | — | — | 1000 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 2000 | 32000 |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | — | — | 4005 | — |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.140 | 0.140 | 8022 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 0.230 | 1.900 | 46272 | 384 |
| unmatched_or_unknown | observed at profiler resolution | 83.880 | 1144.830 | 583024 | 6401758 |

Folded totals: CPU self 84.250% and inclusive 1146.870%, allocation calls 662327, allocation peak bytes 6434142; process-exit Heaptrack residue `2.82K`. Payload flow is 25000 bytes submitted and 25000 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### failure-containment

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 788 | — |
| host context and log calls | observed at profiler resolution | — | — | 28 | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 92 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 0.230 | 0.230 | 185 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 9.480 | 10.630 | 42448 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 89.760 | 642.930 | 38248 | 818474 |

Folded totals: CPU self 99.470% and inclusive 653.790%, allocation calls 82119, allocation peak bytes 2605901; process-exit Heaptrack residue `2.82K`. Payload flow is 892 bytes submitted and 664 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

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
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 0.220 | 1.300 | 517 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.220 | 0.880 | 1046 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 7.340 | 32.910 | 42784 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 91.850 | 986.930 | 93897 | 818450 |

Folded totals: CPU self 99.630% and inclusive 1022.020%, allocation calls 140936, allocation peak bytes 2605877; process-exit Heaptrack residue `2.82K`. Payload flow is 3584 bytes submitted and 3584 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### at-capacity-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | 262 |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 1728 | — |
| host context and log calls | not observed at profiler resolution | — | — | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 192 | — |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 3.860 | 3.860 | 847 | 384 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | 0.260 | 0.260 | 790 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 7.520 | 32.320 | 42656 | 1786781 |
| unmatched_or_unknown | observed at profiler resolution | 88.270 | 798.690 | 53765 | 818480 |

Folded totals: CPU self 99.910% and inclusive 835.130%, allocation calls 99982, allocation peak bytes 2605907; process-exit Heaptrack residue `2.82K`. Payload flow is 5164 bytes submitted and 2572 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

### queued-contention

CPU self is `perf report --no-children`; CPU inclusive is `perf report` with children. Inclusive values can overlap and need not sum to 100%. Heaptrack scans each root-to-leaf folded stack from its allocation leaf, skips allocator/container/runtime plumbing, and classifies only the first remaining owner frame. `unmatched_or_unknown` is deliberately retained.

| Contributor | Observation | CPU self % | CPU inclusive % | Allocation calls | Allocation peak bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| capsule parsing and digest validation | observed at profiler resolution | — | — | 4 | — |
| WIT lifting, lowering, and payload copies | not observed at profiler resolution | — | — | — | — |
| activation envelope and metadata handling | observed at profiler resolution | — | — | 5184 | — |
| host context and log calls | observed at profiler resolution | 0.220 | 0.220 | — | — |
| result mapping and diagnostics | observed at profiler resolution | — | — | 576 | 13476 |
| resource reclamation and cell disposition | not observed at profiler resolution | — | — | — | — |
| pool/queue coordination and runtime scheduling | observed at profiler resolution | 3.780 | 4.020 | 2108 | 362488 |
| store, limiter, host state, instance, and import construction | observed at profiler resolution | — | — | 2326 | — |
| Wasmtime engine and component preparation | observed at profiler resolution | 5.350 | 14.630 | 43424 | 384 |
| unmatched_or_unknown | observed at profiler resolution | 90.410 | 454.760 | 95970 | 2647225 |

Folded totals: CPU self 99.760% and inclusive 473.630%, allocation calls 149592, allocation peak bytes 3023573; process-exit Heaptrack residue `2.82K`. Payload flow is 19236 bytes submitted and 11460 bytes returned; it is not labelled as copied bytes without a narrow WIT/copy symbol.

A dash means that profiler stream did not directly observe the category; it is not a measured zero-cost result. In particular, absent WIT/payload owner frames are reported as not observed rather than proof that lifting, lowering, or copying cost zero bytes.

## Experiment matrix

| Candidate | Runs | Prep us | Warm P50 us | At-cap/s | Queued/s | Fixed RSS | Prep Δ RSS | Peak RSS | Fixed VM | Prep Δ VM | Peak VM | Post-release Δ RSS / VM | Peak threads / sockets | Cache control | Topology / containment | #38 result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| worker-cell-1w-1c | 3 | 48949 | 174 | 317.121 | 614.203 | 5562368 | 12038144 | 17817600 | 89894912 | 71741440 | 162168832 | 12349440 / 72163328 | 3 / 0/0 | cache_hit; second=22 | 1w/1c; hard invariants pass | not_applicable_for_phase0_calibration |
| worker-cell-2w-2c | 7 | 49772 | 166 | 617.236 | 1062.707 | 5505024 | 11939840 | 17985536 | 159117312 | 71745536 | 231661568 | 12288000 / 72433664 | 4 / 0/0 | cache_hit; second=23 | 2w/2c; hard invariants pass | inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band |
| worker-cell-2w-4c | 3 | 49260 | 129 | 910.626 | 1160.871 | 5373952 | 12001280 | 18071552 | 159117312 | 71872512 | 231788544 | 12619776 / 72560640 | 4 / 0/0 | cache_hit; second=23 | 2w/4c; hard invariants pass | not_applicable_for_phase0_calibration |
| worker-cell-4w-2c | 3 | 48803 | 154 | 608.952 | 998.523 | 5488640 | 12075008 | 18411520 | 297562112 | 71749632 | 370642944 | 12722176 / 72970240 | 6 / 0/0 | cache_hit; second=22 | 4w/2c; hard invariants pass | not_applicable_for_phase0_calibration |
| on-demand-cow-disabled | 3 | 51478 | 160 | 638.408 | 1072.474 | 5398528 | 12062720 | 18030592 | 159117312 | 71733248 | 231649280 | 12562432 / 72425472 | 4 / 0/0 | cache_hit; second=22 | 2w/2c; hard invariants pass | not_applicable_for_phase0_calibration |
| pooling-cow-disabled | 3 | 56702 | 135 | 630.111 | 1069.900 | 5431296 | 12410880 | 18378752 | 159117312 | 211505152 | 371421184 | 12951552 / 212180992 | 4 / 0/0 | cache_hit; second=22 | 2w/2c; hard invariants pass | not_applicable_for_phase0_calibration |
| pooling-cow-enabled | 3 | 57400 | 120 | 642.656 | 1075.445 | 5357568 | 12492800 | 18350080 | 159117312 | 211513344 | 371429376 | 12902400 / 212185088 | 4 / 0/0 | cache_hit; second=22 | 2w/2c; hard invariants pass | not_applicable_for_phase0_calibration |
| prepared-cache-disabled | 3 | 50889 | 184 | 580.117 | 967.800 | 5509120 | 11927552 | 18194432 | 159117312 | 71745536 | 231661568 | 12472320 / 72433664 | 4 / 0/0 | disabled_cold_control; second=n/a | 2w/2c; hard invariants pass | not_applicable_for_phase0_calibration |

Fixed RSS/VM is the post-runtime, pre-component baseline. Preparation and post-release deltas are measured against that same baseline; peak values scan every retained process snapshot. `Cache control` is a direct same-key second prepare when enabled, or the explicitly non-reusable disabled-cache control. Every row retains the actual throughput values and complete canonical containment/reclamation checks in `aggregate.json`.

Each candidate retains per-run command provenance, complete measurement identity, and host/toolchain context in `aggregate.json`. The fixed worker-cell-2w-2c reference candidate has at least 7 exact-identity runs and is the only candidate eligible for an advisory-band result. Intentional alternate configurations are Phase 1 experiments and receive no Phase 0 advisory-band calculation.

## Decisions and Phase 1 handoff

### fixed 2-worker/2-cell on-demand configuration: retain existing default; no new adoption

It preserves the measured fixed topology and fresh-store isolation. The 7-run default candidate is reference-equivalent to the calibration and confirms the already selected Phase 0 configuration; it does not introduce a new runtime behavior. #39 runs the final 3x100k resource soak against this configuration.

### bounded preparation/cache reuse versus cold preparation: retain existing setting; no new adoption

The matrix includes a cache-disabled control and the targeted cold-preparation profile. The cache-disabled variant is an explicitly separate Phase 1 experiment, so the existing bounded immutable cache remains the reference setting. #9 generalizes the cache key, policy, eviction, and multi-component compatibility proof.

### worker/cell capacity ratios: carry as configurable Phase 1 experiment

The matrix retains fixed ratios as explicitly non-reference Phase 1 experiments and does not select a universal winner. #8 owns configuration, fairness, and fixed multi-class capacity policy.

### Wasmtime pooling allocator: defer

The experiment has an explicit fixed upper bound and no retained linear-memory allowance, but it changes node-fixed mapping and reset behavior; it is not a comparison against the selected reference. #9 must provide generalized pooling limits, density evidence, and a reset/isolation proof before any production choice.

### copy-on-write initialized memory: carry as configurable Phase 1 experiment

Linux support is profiled explicitly, but its parallel-memory tradeoff is workload-dependent and belongs to the explicitly separate Phase 1 experiment scope. #9 owns target-aware Wasmtime policy and must retain a safe non-COW fallback.

### avoidable activation-path allocations and payload copies: defer

Heaptrack evidence and source-attribution maps identify the current boundaries, but removing copies before the Phase 1 generic value codec and lifecycle shapes exist risks changing contracts or attribution. #9 owns canonical value mapping; #11 owns activation-envelope/lifecycle ownership and cleanup.

### store/instance reuse, persistent AOT artifacts, compiler caches, snapshots, and native execution: reject

These candidates require a new reset/isolation or provenance proof and are forbidden from silently entering Phase 0. Trusted AOT supply-chain work is Phase 2; fresh stores and instances remain mandatory in #9.

## Guardrails

The final Phase 0 configuration remains: fixed node-owned workers and cells; bounded queues, caches, logs, diagnostics, and timing history; a fresh store, limiter, host state, activation context, import table, and instance for every invocation; affirmative cleanup before cell reuse; and no per-service process, thread, listener, connection, runtime instance, or persistent guest memory. Persistent AOT artifacts, provenance-sensitive compiler caches, snapshots, store/instance reuse, shared mutable guest instances, and native execution were not enabled.

The required #39 resource soak must run after this branch is merged, using its final source tree and the retained default on-demand/COW configuration. It is the long-duration reclamation proof; these finite profiles do not replace it.
