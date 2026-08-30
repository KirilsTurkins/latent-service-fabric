# Phase 0 native-Linux resource plateau soak

**Status:** PASS
**Schema:** `latent.phase0.resource-soak.aggregate.v1`
**Generated:** 2026-08-28T15:34:30+00:00
**Aggregate:** `aggregate.json`

> Observational Phase 0 evidence only. This is not a production SLO, capacity guarantee, or cross-machine claim.

## Source, repetitions, and exact commands

- Published final configuration commit: `6a64f0630cee9afa080d33f376aabadac724fa72`
- Source tree: `d27ff38ebbd891c5be949f54a0047522ed893d20`
- Local execution commit shared by every retained process: `f5829873fb1086806fdaf2254617731e75af51ff`
- Independent native-Linux processes: 3

Exact retained process commands:
- run-01: `/var/tmp/latent-phase0-measurement-target-6a64/release/phase0-soak --capsule /var/tmp/latent-phase0-measurement-target-6a64/phase0-resource-soak/staged-containment/capsule.json --output-json /var/tmp/phase0-soak-native-linux-2026-08-28-6a64f063-final/runs/run-01/raw.json --run-index 1 --source-commit 6a64f0630cee9afa080d33f376aabadac724fa72 --source-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --execution-commit f5829873fb1086806fdaf2254617731e75af51ff --execution-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --final-configuration-commit 6a64f0630cee9afa080d33f376aabadac724fa72`
- run-02: `/var/tmp/latent-phase0-measurement-target-6a64/release/phase0-soak --capsule /var/tmp/latent-phase0-measurement-target-6a64/phase0-resource-soak/staged-containment/capsule.json --output-json /var/tmp/phase0-soak-native-linux-2026-08-28-6a64f063-final/runs/run-02/raw.json --run-index 2 --source-commit 6a64f0630cee9afa080d33f376aabadac724fa72 --source-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --execution-commit f5829873fb1086806fdaf2254617731e75af51ff --execution-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --final-configuration-commit 6a64f0630cee9afa080d33f376aabadac724fa72`
- run-03: `/var/tmp/latent-phase0-measurement-target-6a64/release/phase0-soak --capsule /var/tmp/latent-phase0-measurement-target-6a64/phase0-resource-soak/staged-containment/capsule.json --output-json /var/tmp/phase0-soak-native-linux-2026-08-28-6a64f063-final/runs/run-03/raw.json --run-index 3 --source-commit 6a64f0630cee9afa080d33f376aabadac724fa72 --source-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --execution-commit f5829873fb1086806fdaf2254617731e75af51ff --execution-tree d27ff38ebbd891c5be949f54a0047522ed893d20 --final-configuration-commit 6a64f0630cee9afa080d33f376aabadac724fa72`

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
| run-01 | `runs/run-01/raw.json` | `sha256:46b9003bbd0e8264b39da880d7abb84e2358a6f8e8d92957006fb9e8646a87ce` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-02 | `runs/run-02/raw.json` | `sha256:20e4ffc42bc520595ac14d272b7c1b58d202835eeffdd7600f70028725bfe88a` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-03 | `runs/run-03/raw.json` | `sha256:fafc8c989c9afe1eee4aaab48c741f38b6a1b3ce54aec4aee29f8ed4a2eb1df8` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |

## Calibration applicability and plateau analysis

The issue #38 host/configuration identity is strictly matched, so its byte-scale advisory bands are applied to RSS, VM, and available PSS/private metrics.
The raw process environment reconciles with every before/after host observation, and complete descriptor-lifecycle baselines are retained.
Host reconciliation: **PASS**.

The raw interval series retains rolling ranges, peak, final-window delta, and a Theil-Sen robust late-window slope per run. PSS/private use the RSS byte-scale band only when calibration applicability is matched because #38 did not collect separate PSS/private bands.

| Metric | Availability | Peak median | Final-window delta median | Late slope median | Decision |
|---|---|---:|---:|---:|---|
| rss_bytes | available | 18006016.0 | 8192.0 | 364.2688 | pass |
| virtual_memory_bytes | available | 231796736.0 | 0.0 | 0.0000 | pass |
| pss_bytes | available | 15681536.0 | 8192.0 | 364.2688 | pass |
| private_bytes | available | 15523840.0 | 8192.0 | 364.2688 | pass |
| prepared_cache_source_bytes | available | 27616.0 | 0.0 | 0.0000 | observed |
| backend_timing_store_entries | available | 0.0 | 0.0 | 0.0000 | observed |
| active_leases | available | 0.0 | 0.0 | 0.0000 | observed |
| queue_depth | available | 0.0 | 0.0 | 0.0000 | observed |

## Run-level variability

Robust outliers are retained for review. They are not discarded or silently relabelled.
- virtual_memory_bytes: run-03 (within calibrated late-window bound).
- pss_bytes: run-02 (within calibrated late-window bound).

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
| run-01 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.07 MiB (17895424 bytes) | 14.90 MiB (15621120 bytes) | 14.77 MiB (15482880 bytes) | 220.95 MiB (231686144 bytes) |
| run-01 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.18 MiB (18018304 bytes) | 14.90 MiB (15625216 bytes) | 14.76 MiB (15474688 bytes) | 220.41 MiB (231116800 bytes) |
| run-02 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 16.82 MiB (17637376 bytes) | 14.60 MiB (15304704 bytes) | 14.45 MiB (15151104 bytes) | 220.95 MiB (231686144 bytes) |
| run-02 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.00 MiB (17825792 bytes) | 14.60 MiB (15312896 bytes) | 14.44 MiB (15142912 bytes) | 220.41 MiB (231116800 bytes) |
| run-03 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.14 MiB (17977344 bytes) | 14.85 MiB (15570944 bytes) | 14.70 MiB (15413248 bytes) | 220.96 MiB (231690240 bytes) |
| run-03 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.32 MiB (18165760 bytes) | 14.86 MiB (15579136 bytes) | 14.69 MiB (15405056 bytes) | 220.41 MiB (231120896 bytes) |

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
- A calibration-inconclusive archive must not be used to claim that its RSS/PSS/private/VM series is inside the #38 advisory band.

## Conclusion

All independent native-Linux processes passed every hard invariant, the full measured and terminal FD checks, and bounded topology validation; no calibrated material RSS/PSS/private/VM growth was detected for the strictly matched configuration. This is a Phase 0 plateau observation for the recorded configuration, not a production claim.
