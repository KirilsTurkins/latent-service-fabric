# Phase 0 hot-path profiling evidence

**Status:** pass. This is optimization evidence, not a production SLO, cross-platform claim, or capacity commitment.

## Profile coverage

| Workload | CPU profile | Allocation/copy evidence | Prep (us) | Warm P50 (us) | Cleanup P50 (us) | Allocation calls | Process-exit Heaptrack total | Top sampled CPU |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| cold-preparation | `profiles/cold-preparation/perf/perf-report.txt` | `profiles/cold-preparation/allocation/heaptrack-report.txt` | 48555 | 191 | 30 | 64321 | 2.82K | 33.35% [k] vma_merge_new_range |
| first-activation | `profiles/first-activation/perf/perf-report.txt` | `profiles/first-activation/allocation/heaptrack-report.txt` | 66329 | 195 | 41 | 64260 | 2.82K | 54.02% [k] established_get_first |
| warm-execution | `profiles/warm-execution/perf/perf-report.txt` | `profiles/warm-execution/allocation/heaptrack-report.txt` | 52552 | 138 | 21 | 1843914 | 2.82K | 75.11% [k] established_get_first |
| failure-containment | `profiles/failure-containment/perf/perf-report.txt` | `profiles/failure-containment/allocation/heaptrack-report.txt` | 48868 | 245 | 26 | 105251 | 2.82K | 19.48% [k] established_get_first |
| cleanup | `profiles/cleanup/perf/perf-report.txt` | `profiles/cleanup/allocation/heaptrack-report.txt` | 49401 | 234 | 25 | 105250 | 2.82K | 24.87% [.] 0x00007fdd38a663f9 |
| contention | `profiles/contention/perf/perf-report.txt` | `profiles/contention/allocation/heaptrack-report.txt` | 50284 | 122 | 36 | 292828 | 2.82K | 15.42% [.] 0x00007f436408a153 |

Each profile invokes the real shared Phase 0 composition and retains a passing baseline raw document beside both the symbolized `perf` and `heaptrack` artifacts. Heaptrack allocation-call totals and a dedicated process-exit leak report are mandatory, so an unreadable compressed trace cannot be mistaken for zero allocations. The baseline's hard topology, containment, recovery, cleanup, and reclamation checks are binary prerequisites; profiling never converts them into tolerances.

## Principal contributors and interpretation

The retained reports quantify component preparation at 48555-66329 us, warm activation P50 at 122-245 us, and post-invocation cleanup P50 at 21-41 us across these profile processes. Wasmtime/Cranelift preparation, store/instance construction, WIT lifting/copies, host/context work, result mapping, reclamation, and pool/runtime scheduling are indexed in the aggregate attribution map with the matching raw symbol lines.

The top sampled CPU entry is shown for each workload so benchmark-observer cost is explicit. Full Phase 0 proof intentionally scans Linux process resources (including socket state); those samples can dominate a long warm process and are not silently reclassified as production activation cost. They remain in the profile because the hard resource/topology proof remains mandatory, and no optimization decision is based on removing that proof.

## Experiment matrix

| Candidate | Runs | Preparation median (us) | Warm P50 (us) | Peak RSS (bytes) | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| worker-cell-1w-1c | 3 | 49700 | 130 | 19374080 | inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band |
| worker-cell-2w-2c | 3 | 49548 | 130 | 19378176 | inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band |
| worker-cell-2w-4c | 3 | 49823 | 130 | 19775488 | inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band |
| worker-cell-4w-2c | 3 | 49799 | 145 | 19816448 | inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band |
| on-demand-cow-disabled | 3 | 50081 | 115 | 19652608 | inside_advisory_band, inside_advisory_band, inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band |
| pooling-cow-disabled | 3 | 57320 | 101 | 19873792 | inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band |
| pooling-cow-enabled | 3 | 56933 | 114 | 19947520 | inside_advisory_band, inside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band, outside_advisory_band |

No new runtime optimization is adopted from this matrix unless it has at least 7 comparable runs, passes every hard invariant, stays within documented fixed/peak-memory costs, and clears the #38 calibrated noise envelope. This archive does not meet the run-count threshold for adoption, so it records decisions without promoting a faster single or small-set result.

## Decisions and Phase 1 handoff

### fixed 2-worker/2-cell on-demand configuration: adopt now

It preserves the measured fixed topology and fresh-store isolation; this archive introduces no runtime behavior change. #39 runs the final 3x100k resource soak against this configuration.

### bounded preparation/cache reuse versus cold preparation: adopt now

The cache is node-owned, bounded, and stores prepared immutable state only; stores and instances remain fresh per activation. #9 generalizes the cache key, policy, eviction, and multi-component compatibility proof.

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

## Attribution map

The machine-readable aggregate records matching symbol lines from both tools for capsule/digest validation, Wasmtime preparation, store/instance construction, envelope/metadata work, WIT lifting/lowering/copies, host calls, result mapping, reclamation, and pool/runtime coordination. An empty automatic match is explicitly a review item, not an assertion of zero cost.

## Guardrails

The final Phase 0 configuration remains: fixed node-owned workers and cells; bounded queues, caches, logs, diagnostics, and timing history; a fresh store, limiter, host state, activation context, import table, and instance for every invocation; affirmative cleanup before cell reuse; and no per-service process, thread, listener, connection, runtime instance, or persistent guest memory. Persistent AOT artifacts, provenance-sensitive compiler caches, snapshots, store/instance reuse, shared mutable guest instances, and native execution were not enabled.

The required #39 resource soak must run after this branch is merged, using its final source tree and the retained default on-demand/COW configuration. It is the long-duration reclamation proof; these finite profiles do not replace it.
