# Phase 0 native-Linux resource plateau soak

**Status:** PASS
**Schema:** `latent.phase0.resource-soak.aggregate.v1`
**Generated:** 2026-08-30T14:39:49+00:00
**Aggregate:** `/home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/.soak-package.package-fgn_17k_/evidence/aggregate.json`

> Observational Phase 0 evidence only. This is not a production SLO, capacity guarantee, or cross-machine claim.

## Source, repetitions, and exact commands

- Published final configuration commit: `52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
- Source tree: `cac3ececdbd0b5734691c30c0283fccff169a5f5`
- Local execution commit shared by every retained process: `52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
- Independent native-Linux processes: 3

Exact retained process commands:
- run-01: `/home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/collector/phase0-soak --capsule /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-build/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/runs/run-01/raw.json --run-index 1 --source-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --source-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --published-source-ref refs/heads/fix/phase0-gate-validation --published-source-ref-head 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --final-configuration-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
- run-02: `/home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/collector/phase0-soak --capsule /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-build/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/runs/run-02/raw.json --run-index 2 --source-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --source-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --published-source-ref refs/heads/fix/phase0-gate-validation --published-source-ref-head 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --final-configuration-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
- run-03: `/home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/collector/phase0-soak --capsule /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-build/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/phase0-pr48-evidence-final-2026-08-30.TwThmQ/soak-raw/runs/run-03/raw.json --run-index 3 --source-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --source-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --published-source-ref refs/heads/fix/phase0-gate-validation --published-source-ref-head 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 --execution-tree cac3ececdbd0b5734691c30c0283fccff169a5f5 --final-configuration-commit 52ac47542a05c0a1263f78a14c04a5c2e6b761f3`

## Reference environment and toolchain

| Field | Recorded value |
|---|---|
| Operating system / architecture | `linux` / `x86_64` |
| CPU | AMD Ryzen 3 3200G with Radeon Vega Graphics |
| Logical CPUs | 4 |
| Memory | 15.55 GiB (16699981824 bytes) |
| Kernel | Linux 7.1.5-201.fc44.x86_64 #1 SMP PREEMPT_DYNAMIC Tue Jul 28 14:16:30 UTC 2026 x86_64 GNU/Linux |
| Virtualization | {'systemd_detect_virt': 'none', 'systemd_detect_virt_container': 'none', 'systemd_detect_virt_vm': 'none', 'wsl_detected': False} |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14)<br>binary: rustc<br>commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452<br>commit-date: 2026-07-14<br>host: x86_64-unknown-linux-gnu<br>release: 1.97.1<br>LLVM version: 22.1.6 |
| Cargo | cargo 1.97.1 (c980f4866 2026-06-30) |
| Target / build profile | `x86_64-unknown-linux-gnu` / `release` |
| Wasmtime | 47.0.3 (workspace pin) |
| Allocator observation | {'ld_preload': 'unset', 'malloc_conf': 'unset', 'observation': 'When no source global allocator is found and LD_PRELOAD is unset, Rust uses its standard allocator backed by the platform allocator.', 'source_global_allocator_lookup': 'completed', 'source_global_allocator_matches': []} |
| Fixture | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` (27616 bytes) |

## Effective configuration, bounds, and sampling schedule

| Setting | Effective value |
|---|---|
| Warm-up activations (excluded) | 1000 |
| Normal measured activations | 100000 |
| Normal activations per batch | 100 |
| Saturation interval | after every 10 normal batches |
| Fixed pool / queue capacity | 2 / 4 |
| Runtime workers | 2 |
| Fuel | 1000000000000 |
| Memory grant / pressure grant | 16.00 MiB (16777216 bytes) / 4.00 MiB (4194304 bytes) |
| Timeout / cancellation delay | 25 ms / 5 ms |
| Prepared cache / Wasmtime allocator / initialized-memory COW | `true` / `on_demand` / `true` |

Retained-state numeric bounds:

| State | Limit | Evidence source |
|---|---|---|
| Component input | 64.00 MiB (67108864 bytes) | recorded raw config |
| Prepared cache | 1 entry; 64.00 MiB (67108864 bytes) | recorded raw config |
| Invocation log | 64 entries; 64.00 KiB (65536 bytes) | recorded raw config |
| Retained log | 64 entries; 64.00 KiB (65536 bytes) | recorded raw config |
| Backend timing store | 256 entries | recorded raw snapshot |

Sampling schedule:
- 10 excluded warm-up checkpoints of 100 activations.
- 1000 normal measured checkpoints of 100 activations.
- Every 10 normal checkpoints, one at-capacity batch (2 activations) and one bounded-queue batch (6 activations) run before their own checkpoints.
- Retained totals per process: 100 at-capacity observations, 100 bounded-queue observations, 800 additional saturation activations, and 1210 batch-invariant checkpoints (plus post-prepare and post-release snapshots).

## Raw evidence

The raw paths below are losslessly retained in `raw-evidence.tar.zst`; verify its `raw-evidence.manifest.sha256` and extract it before inspection.

| Run | Raw file | SHA-256 | Component digest |
|---|---|---|---|
| run-01 | `runs/run-01/raw.json` | `sha256:e0731f5d085b5838254821c81be11e8b9ec097d2f2c73c2be9bb1a5e92ec4672` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-02 | `runs/run-02/raw.json` | `sha256:132b4b16d7974de4310148c5d09bde78c066eb99a9d08d435ec1e5d71f504472` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-03 | `runs/run-03/raw.json` | `sha256:e3a628cf2ccc42ac950ca44097883d8265f9f25bb6a7e04138e5d07e63404d5b` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |

## Calibration applicability and plateau analysis

The issue #38 host/configuration identity is strictly matched, so its byte-scale advisory bands are applied to RSS, VM, and available PSS/private metrics.
The raw process environment reconciles with every before/after host observation, and complete descriptor-lifecycle baselines are retained.
Host reconciliation: **PASS**.

The raw interval series retains rolling ranges, peak, final-window delta, and a Theil-Sen robust late-window slope per run. PSS/private use the RSS byte-scale band only when calibration applicability is matched because #38 did not collect separate PSS/private bands.

| Metric | Availability | Peak median | Final-window delta median | Late slope median | Decision |
|---|---|---:|---:|---:|---|
| rss_bytes | available | 18178048.0 | 8192.0 | 364.2688 | pass |
| virtual_memory_bytes | available | 231825408.0 | 0.0 | 0.0000 | pass |
| pss_bytes | available | 15572992.0 | 8192.0 | 364.2688 | pass |
| private_bytes | available | 15536128.0 | 8192.0 | 364.2688 | pass |
| prepared_cache_source_bytes | available | 27616.0 | 0.0 | 0.0000 | observed |
| backend_timing_store_entries | available | 0.0 | 0.0 | 0.0000 | observed |
| active_leases | available | 0.0 | 0.0 | 0.0000 | observed |
| queue_depth | available | 0.0 | 0.0 | 0.0000 | observed |

## Run-level variability

No robust cross-run peak or final-window-delta outlier was identified.

## Topology, descriptors, explicit release, and shutdown

File descriptors: **PASS**; the measured window, post-release-to-shutdown, and complete descriptor lifecycle baseline comparisons must have no unexplained growth.
Descriptor lifecycle baselines: **PASS**; the final measured FD count must not exceed the post-warm-up baseline, and post-release/post-shutdown counts must not exceed the serialized pre-runtime baseline in every independent process.

| Run | Pre-runtime FDs | Post-warm-up FDs | Final measured FDs | Post-release FDs | Post-shutdown FDs | Lifecycle status |
|---|---:|---:|---:|---:|---:|---|
| run-01 | 4 | 5 | 5.0 | 4 | 4 | pass |
| run-02 | 4 | 5 | 5.0 | 4 | 4 | pass |
| run-03 | 4 | 5 | 5.0 | 4 | 4 | pass |
- measured process_count: **PASS**
- measured child_process_count: **PASS**
- measured thread_count: **PASS**
- measured open_socket_count: **PASS**
- measured listening_socket_count: **PASS**

| Run | Stage | Proc. | Children | Threads | FDs | Open sockets | Listeners | RSS | PSS | Private | VM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| run-01 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.23 MiB (18067456 bytes) | 14.75 MiB (15462400 bytes) | 14.71 MiB (15425536 bytes) | 220.97 MiB (231706624 bytes) |
| run-01 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.35 MiB (18190336 bytes) | 14.74 MiB (15455232 bytes) | 14.70 MiB (15417344 bytes) | 220.43 MiB (231137280 bytes) |
| run-02 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.08 MiB (17907712 bytes) | 14.70 MiB (15413248 bytes) | 14.67 MiB (15384576 bytes) | 220.98 MiB (231714816 bytes) |
| run-02 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.13 MiB (17965056 bytes) | 14.69 MiB (15406080 bytes) | 14.66 MiB (15376384 bytes) | 220.44 MiB (231145472 bytes) |
| run-03 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.37 MiB (18214912 bytes) | 14.86 MiB (15581184 bytes) | 14.82 MiB (15544320 bytes) | 220.99 MiB (231723008 bytes) |
| run-03 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.49 MiB (18337792 bytes) | 14.85 MiB (15574016 bytes) | 14.82 MiB (15536128 bytes) | 220.45 MiB (231153664 bytes) |

## Method and explicit limits

- The command is explicit native-Linux soak work and intentionally does not run in shared PR smoke CI.
- Every normal and saturation batch uses the real shared Phase 0 runtime, bounded fixed pool, Wasmtime backend, prepared cache, activation runner, and a fresh store per activation.
- The runner fails on WSL, a container, missing required Linux process/socket probes, a dirty tree, source/tree mismatch, unavailable fixture/toolchain input, test-only output, or an existing archive destination.
- The aggregate rejects missing/duplicate hard checks, mismatched execution commit/tree or run index, raw/host environment disagreement, missing samples, saturation-count/activation-counter disagreement, changed measured topology, measured-window FD growth, a post-release-to-shutdown FD increase, a descriptor value above its retained lifecycle baseline, and invalid terminal process topology.
- New archives must retain the selected prepared-cache, Wasmtime allocator, initialized-memory COW, retained-state-limit, raw virtualization, pre-runtime, and post-warm-up descriptor-baseline fields. The sole 6250b978/65ba3412 historical fallback is explicitly incomplete where it cannot prove a lifecycle comparison.
- A material calibrated growth result must identify a retaining subsystem or focused issue; the allowance is never raised to clear a run.

## Unsupported measurements and conclusions

- Allocator-internal statistics are unsupported until a safe allocator-specific probe is configured.
- This finite single-host process evidence does not prove arbitrary-duration leak freedom, multi-node behavior, cluster scaling, 100,000-service density, state throughput, remote-call latency, networking, autoscaling, or call-graph fusion.
- It is not a production SLO, release promise, capacity guarantee, competitive-performance result, cross-machine result, or cross-platform result.
- An archive without a strictly matched calibration must not be used to claim that its RSS/PSS/private/VM series is inside the #38 advisory band.

## Conclusion

All independent native-Linux processes passed every hard invariant, the full measured and terminal FD checks, and bounded topology validation; no calibrated material RSS/PSS/private/VM growth was detected for the strictly matched configuration. This is a Phase 0 plateau observation for the recorded configuration, not a production claim.
