# Scheduler queue storage, cancellation and retirement

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

Direct queued-entry locations removed the measured cancellation scans and element shifts. Timing was mixed: the one-tenant cancellation median fell from **37.8615 to 36.6405 microseconds**, while the eight-tenant median rose from **30.0755 to 42.6785 microseconds**. Selected cancellation allocations were unchanged. The full comparison passed **14 collectors and 9,128 logical offers, with zero guest Invokes**. These results support the mechanical work reduction and ownership fix; they do not establish uniformly faster scheduling or lower memory use.

The scheduler stores queue entries and tenant rotation links in bounded reusable slots, with sequence-checked queued locations and an indexed tenant lookup. It preserves the original **O(n) within-tenant priority/deadline/aging winner scan**, round-robin order and reserved logical queue depth across an open pool call. Restoring a selected entry uses its original sequence and the current tenant. Stale owners cannot remove a replacement registration.

Retired cancellation registrations are detached under the state mutex and their final owners destroyed after unlocking, following entry/permit disposal. The retained before-fix regression failed its nonhanging locked-state witness; the fixed version passed release, Drop/quarantine and pre-execution reclaim. The selected-cancellation race test preserves admission ownership: early same-ID admission remains `AlreadyExists`; another ID can reuse the physical slot; the original ID becomes admissible after the old permit is disposed. Arenas retain bounded high-water capacity after drain.

## Fixed population and boundaries

Full collection took **24.381072142 seconds**. Its 9,128 offers comprise 8,720 load offers (including 64 warmups), 272 normal cancellation-storm offers and 136 separately profiled storm offers. One matched pair runs per case; normal pairs alternate first arm, then the allocation pair runs control/candidate. There are no repeated-pair confidence intervals or production SLO claims.

Load uses four real scheduler cells, a requested 10 ms assignment hold, queue capacity 32, pending capacity 1/64 and the original one-second admission deadline. Closed T1/C1 measures 128 offers; saturated T1 and T32 each schedule 2,000 at 1,000/s; reference T32 schedules 200 at 100/s. Each load child has eight separate warmups. Actual holds, scheduling lag and every outcome remain in the [load table](analysis/load.csv); rates use the measured window including final drain.

Each T1/T8 storm holds four assignments and queues 64 original futures. It issues 32 Cancel calls, settles those same 32 futures as cancelled, then explicitly releases 36 assignments. Queue capacity is 64. Each child performs one separately counted shutdown. All original futures and owned resources settle; no offers are replaced or retried.

Both saturated cases/arms showed actual backlog, scheduler rejection and releases; both references completed every offered request. Both selected profiles had actual nonzero named allocation coverage. Thus full population completion and acceptance qualification both passed. These are scheduler service-model measurements, not guest invocation throughput.

## Load results

All values below are control -> candidate. Enqueue-to-result includes caller polling; it is not an exact internal queue-wait or mutex-wait measurement. All measured load offers were admitted and reached enqueue, with zero admission errors or client backpressure. The rejection column is scheduler rejection; there were no measured timeouts. Warmups are excluded from this table.

| Case | Offers per arm | Released | Rejected | Released/s | Released p50, ms | Released p99, ms | All enqueue p99, ms |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| closed-one | 128 | 128 -> 128 | 0 -> 0 | 88.144 -> 88.910 | 0.026 -> 0.023 | 0.102 -> 0.080 | 0.102 -> 0.080 |
| saturated-one | 2000 | 744 -> 748 | 1256 -> 1252 | 355.194 -> 357.471 | 88.533 -> 88.169 | 92.710 -> 91.266 | 92.050 -> 90.855 |
| saturated-many | 2000 | 748 -> 746 | 1252 -> 1254 | 356.920 -> 354.940 | 79.255 -> 78.672 | 165.815 -> 179.116 | 152.143 -> 157.790 |
| reference-many | 200 | 200 -> 200 | 0 -> 0 | 99.865 -> 99.930 | 0.026 -> 0.032 | 0.094 -> 0.149 | 0.094 -> 0.149 |

Closed and saturated-T1 tails improved in this pair. Saturated-T32 released p99 and the reference median/tail were worse. At saturation most all-enqueue results are fast rejections, so their median cannot represent successful queue service. The [complete companion](analysis/analysis.json) and [per-tenant table](analysis/per-tenant.csv) preserve p50/p95/p99/max, denominators, scheduling lag, observed hold, null distributions and every tenant outcome. These small case populations do not establish stable production tails.

## Cancellation work and timing

The normal 32-cancellation/settlement window alone enables work counters. Setup and drain are excluded from the counters. Counter maintenance contributes to normal storm timing and its cost differs with the counted work; these counters do not measure instructions, lock-hold time or contention. Each observed frame completed in one actual poll, with 32 direct unlinks in both arms.

| Tenants | Entry visits | Shifted entry slots | Linear tenant visits | Frame time, us | Settlement p50, us | Settlement p95, us | Settlement p99, us |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | 544 -> 0 | 1008 -> 0 | 32 -> 0 | 65.955 -> 62.103 | 37.861 -> 36.641 | 51.421 -> 48.800 | 52.849 -> 49.679 |
| 8 | 712 -> 0 | 112 -> 0 | 144 -> 0 | 56.383 -> 73.963 | 30.076 -> 42.678 | 43.490 -> 56.734 | 44.516 -> 57.893 |

Tenant-index lookups, shifted tenant slots and winner comparisons were zero in these cancellation windows in both arms. The zero winner count reflects the full-pool window, not removal of the unchanged winner scan. The [complete cancellation table](analysis/cancellation.csv) retains all counters, frame timing and whole-storm outcomes, including the slower eight-tenant candidate whole scenario.

## Whole-process resources and separate profiles

Normal resources below include the entire libtest process: fixture/runtime setup, output and different product test descriptors. They do not isolate per-request CPU or production node RSS. In these observations completion RSS, sampled maximum and kernel high-water RSS were equal; this does not make sampling an exact operation-local peak.

| Normal case | Process CPU, ms | Completion / observed / kernel-HWM RSS, MiB |
| --- | --- | --- |
| closed-one | 27.182 -> 23.746 | 4.500 -> 4.875 |
| saturated-one | 185.080 -> 174.432 | 24.750 -> 24.625 |
| saturated-many | 173.869 -> 188.462 | 25.000 -> 25.000 |
| reference-many | 33.919 -> 39.052 | 5.125 -> 5.000 |
| cancel-one | 4.809 -> 5.093 | 4.375 -> 4.375 |
| cancel-many | 4.765 -> 6.168 | 4.500 -> 4.750 |

The [normal resource table](analysis/normal-resources.csv) preserves exact bytes and CPU. Candidate CPU and RSS are not uniformly lower. Bounded reusable capacity after drain remains a tradeoff; no production memory ceiling is established.

The separate T8 Heaptrack pair disables work counters. Both profiles observe the actual `latent_scheduler::local::measurement::measured_cancel_and_settle` poll frame, with 32 cancellations and 32 original settlements, one poll and zero unresolved selected allocations. Selected peaks count simultaneously live allocation origins, not temporary scratch. Profiler wall/CPU is excluded from normal timing conclusions.

| Allocation scope | Count | Allocated B | Live peak B | Remaining count / B |
| --- | --- | --- | --- | --- |
| Selected cancellation/settlement | 224 -> 224 | 21,760 -> 21,760 | 20,992 -> 20,992 | 0 / 0 -> 0 / 0 |
| Whole process | 13,776 -> 13,758 | 1,622,973 -> 1,643,919 | 689,072 -> 689,084 | 3 / 928 -> 3 / 928 |

The [allocation table](analysis/allocation.csv) retains exact coverage and residuals. Selected residual zero does not imply no whole-process retention. This pair demonstrates **no selected allocation improvement**; whole allocated bytes and live peak increased slightly.

## Sources and validation

Control was `7ddc41779cd0648a14626b1e558a7bff08ba3fe2`; candidate and harness were `77c071550160cb661864c828d825b3fd08cf25f0`. Common measurement, work-counter and bounded helper sources were byte-identical. Clean builds and the retained source closure bind Cargo.lock, source trees, build recipe and executable identities. The control ELF was 20,134,232 B, SHA256 `ae264b1e0f6bb265f106443f77ad54742437efa3db9cae6ca72a9d25d495f389`; candidate was 21,046,280 B, SHA256 `1f731e4dcbf18e977f876a82c5931805d2a3b3b3f857b93670d63b8862f956a4`.

The environment was Linux x86_64 in Docker on WSL2 kernel 6.6.87.2, Intel Core i7-11850H, 16 visible logical CPUs and 33,233,743,872 B host memory. The visible cgroup had a four-CPU quota (`400000 100000`), cpuset 0-15 and no leaf memory maximum. Shared cgroup readings include other work and are not per-collector attribution. Builds used Rust/Cargo 1.97.1, target `x86_64-unknown-linux-gnu`, opt-level 3, 16 codegen units, LTO disabled and symbols retained; profiles used Heaptrack 1.4.0 and zstd 1.5.4. This is not a bare-metal or Kubernetes comparison.

Neutral and matched smoke each passed 14 collectors / 1,344 offers before full collection. Neutral took 11.106249423 s and matched 10.480883640 s; each passed semantic replay and all 31 actual schema documents. Neutral arms used the identical control ELF and each observed 224 selected allocations / 21,760 B. Smoke validates the protocol and coverage, not full acceptance. [Separate witnesses](attempts/README.md) retain the intentional before-fix regression, corrected race-test assumption and smoke inspections.

The [supporting manifest](validation/supporting-manifest.json) records **71 unique passing scheduler checks and one ignored collector**, deduplicating overlapping runs. It links the actual native, Python and regular Clippy logs and receipts. Initial 18 Python checks, six added complete-parser checks and 39 original archive checks are retained as separate scopes. Older scheduler Clippy warnings remain. Final PR-head CI is required before merging; this report does not turn pending CI into a passed result.

## Archive and reproduction

The closed archive passed mandatory Linux semantic roundtrip replay and independent Windows replay, with the source, copied and report package bytes unchanged. Windows replay took **16.538549100 seconds**. The [Linux receipt](validation/linux-package.json) records actual exit zero; its duration was not recorded. The [Windows receipt](validation/windows-replay.json) and [copy receipt](publication-receipt.json) retain the actual hashes and completion evidence.

The [member manifest](scheduler/raw-evidence.manifest.json) covers **923 files / 60,893,654 expanded bytes**. The logical gzip is **13,138,362 B**, SHA256 **`6eee8ae0759449fe8261ddb89f148bd3182d04a01a19a3a47b9cdfe998d4a3b1`**, retained in two equal parts bound by the [part manifest](scheduler/raw-evidence.parts.json). The [original aggregate](scheduler/aggregate.json), both clean binaries, build closure and full raw population are retained. Smoke diagnostics are separate from this qualifying package.

Replay from the repository root:

```sh
python tools/validate_phase1_archive.py "${restored_root}/benchmarks/optimization/scheduler-queues/2026-09-11-container-linux-77c0715/scheduler"
```

Use a clean checkout of the exact harness above and fresh directories for collection. Build the two revisions, copy the complete hash-bound build closure including sidecars and executable modes into separate fresh smoke/full roots, and run smoke before full:

```sh
python tools/build_optimization_scheduler.py --profile full --control-ref 7ddc41779cd0648a14626b1e558a7bff08ba3fe2 --candidate-ref 77c071550160cb661864c828d825b3fd08cf25f0 --harness-ref 77c071550160cb661864c828d825b3fd08cf25f0 --output <fresh-build-root> --target-root <fresh-build-parent>
python tools/run_optimization_scheduler.py --profile smoke --builds <smoke-root>/scheduler-builds.json
python tools/run_optimization_scheduler.py --profile full --builds <full-root>/scheduler-builds.json
python tools/validate_optimization_scheduler.py <full-root>/suite.json --aggregate <full-root>/aggregate.json
python tools/package_phase1_evidence.py --source <full-root> --output <fresh-package> --compression-level 9 --split-archive
python benchmarks/optimization/scheduler-queues/2026-09-11-container-linux-77c0715/extract.py <full-root>/aggregate.json <fresh-analysis-directory>
```

The [extractor](extract.py) performs descriptive transformation only, requires the exact qualified sources/population, preserves nulls and checks the original aggregate remains unchanged. [All paired differences](analysis/paired-differences.csv) and [analysis hashes](analysis/manifest.json) remain available. Reproduction does not reuse or overwrite the measured full root.

Bounds remain 64 MiB expanded folded reports, 256 MiB ordinary retained files, 1 GiB retained/expanded archive, four million interpreted records, 4,096 evidence inventory files, 32 MiB raw per child and 8 MiB aggregate, with no extra scratch allowance. Historical archive limits remain unchanged. Unmet timing/allocation/memory improvements remain limitations; actual Docker #111 and Kubernetes #112 comparisons, concise consolidation #113 and Phase 2 follow this final scheduler optimization.
