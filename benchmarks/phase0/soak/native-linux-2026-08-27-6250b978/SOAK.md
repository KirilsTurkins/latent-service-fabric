# Phase 0 native-Linux resource plateau soak

**Status:** INCONCLUSIVE
**Schema:** `latent.phase0.resource-soak.aggregate.v1`
**Generated:** 2026-08-27T19:37:24+00:00
**Aggregate:** `benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/aggregate.json`

> Observational Phase 0 evidence only. This is not a production SLO, capacity guarantee, or cross-machine claim.

## Source, repetitions, and exact commands

- Published final configuration commit: `6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- Source tree: `65ba341221ea89e107a3e0e3c4b0aed7e26efd9b`
- Local execution commit shared by every retained process: `e8fcc441ca96a0f4e66793733a334a6bd4b4eeac`
- Independent native-Linux processes: 3

Exact retained process commands:
- run-01: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-01/raw.json --run-index 1 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- run-02: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-02/raw.json --run-index 2 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- run-03: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-03/raw.json --run-index 3 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`

## Reference environment and toolchain

| Field | Recorded value |
|---|---|
| Operating system / architecture | `linux` / `x86_64` |
| CPU | AMD Ryzen 3 3200G with Radeon Vega Graphics |
| Logical CPUs | 4 |
| Memory | 15.55 GiB (16699981824 bytes) |
| Kernel | Linux 7.1.5-201.fc44.x86_64 #1 SMP PREEMPT_DYNAMIC Tue Jul 28 14:16:30 UTC 2026 x86_64 GNU/Linux |
| Virtualization | {'systemd_detect_virt': 'none', 'systemd_detect_virt_container': 'none', 'wsl_detected': False} |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14)<br>binary: rustc<br>commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452<br>commit-date: 2026-07-14<br>host: x86_64-unknown-linux-gnu<br>release: 1.97.1<br>LLVM version: 22.1.6 |
| Cargo | cargo 1.97.1 (c980f4866 2026-06-30) |
| Target / build profile | `x86_64-unknown-linux-gnu` / `release` |
| Wasmtime | 47.0.3 (workspace pin) |
| Allocator observation | unavailable in retained host observation; process report: {'available': False, 'method': 'not_collected', 'reason': 'allocator-internal statistics are optional and no allocator-specific safe probe is configured'} |
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
| Component input | 64.00 MiB (67108864 bytes) | fixed harness bound verified only for known historical source 6250b978/65ba3412 (v1 raw schema did not serialize this key) |
| Prepared cache | 1 entry; 64.00 MiB (67108864 bytes) | fixed harness bound verified only for known historical source 6250b978/65ba3412 (v1 raw schema did not serialize this key) |
| Invocation log | 64 entries; 64.00 KiB (65536 bytes) | fixed harness bound verified only for known historical source 6250b978/65ba3412 (v1 raw schema did not serialize this key) |
| Retained log | 64 entries; 64.00 KiB (65536 bytes) | fixed harness bound verified only for known historical source 6250b978/65ba3412 (v1 raw schema did not serialize this key) |
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
| run-01 | `runs/run-01/raw.json` | `sha256:ddc02b0cf61896b4a4a80249cb92add139abef392ba31993619f989b7ab6d130` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-02 | `runs/run-02/raw.json` | `sha256:0b7bad4ae32094637d9d8313cb3f8baa20c4b96fc7ac7b0ea9a3eef7dfd4c3f3` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-03 | `runs/run-03/raw.json` | `sha256:4f58c8941db0179bc837d95a38e96cbb9d11defbff92e704387e35f68a521fd9` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |

## Calibration applicability and plateau analysis

**INCONCLUSIVE calibration comparison:** the issue #38 bands are not applied because the required identity is not fully matched and recorded.
- `config.prepared_cache_enabled`: calibration `None`; soak `True` (missing calibration value).
- `config.wasmtime_instance_allocator`: calibration `None`; soak `on_demand` (missing calibration value).
- `config.wasmtime_copy_on_write_images`: calibration `None`; soak `True` (missing calibration value).
- `host.virtualization.systemd_detect_virt_vm`: calibration `none`; soak `None` (missing soak value).
- `host.allocator`: calibration `{'ld_preload': 'unset', 'malloc_conf': 'unset', 'observation': 'When no source global allocator is found and LD_PRELOAD is unset, Rust uses its standard allocator backed by the platform allocator.', 'source_global_allocator_lookup': 'completed', 'source_global_allocator_matches': []}`; soak `None` (missing soak value).
**INCOMPLETE retained evidence:** a future archive must retain the missing identity or descriptor-lifecycle fields before it can support a conclusive plateau claim.
- complete descriptor lifecycle comparison is unavailable for run-01, run-02, run-03.
- run-01, run-02, run-03: after host VM virtualization status is absent.
- run-01, run-02, run-03: after host allocator provenance is absent.
- run-01, run-02, run-03: before host VM virtualization status is absent.
- run-01, run-02, run-03: before host allocator provenance is absent.
- run-01, run-02, run-03: post-warm-up descriptor baseline is absent.
- run-01, run-02, run-03: pre-runtime process baseline is absent.
- run-01, run-02, run-03: raw native-Linux virtualization_kind is absent.
Host reconciliation: **INCOMPLETE**.

The raw interval series retains rolling ranges, peak, final-window delta, and a Theil-Sen robust late-window slope per run. PSS/private use the RSS byte-scale band only when calibration applicability is matched because #38 did not collect separate PSS/private bands.

| Metric | Availability | Peak median | Final-window delta median | Late slope median | Decision |
|---|---|---:|---:|---:|---|
| rss_bytes | available | 18116608.0 | 8192.0 | 364.2688 | observed |
| virtual_memory_bytes | available | 231780352.0 | 0.0 | 0.0000 | observed |
| pss_bytes | available | 15604736.0 | 8192.0 | 364.2688 | observed |
| private_bytes | available | 15421440.0 | 8192.0 | 364.2688 | observed |
| prepared_cache_source_bytes | available | 27616.0 | 0.0 | 0.0000 | observed |
| backend_timing_store_entries | available | 0.0 | 0.0 | 0.0000 | observed |
| active_leases | available | 0.0 | 0.0 | 0.0000 | observed |
| queue_depth | available | 0.0 | 0.0 | 0.0000 | observed |

## Run-level variability

Robust outliers are retained for review. They are not discarded or silently relabelled.
- pss_bytes: run-03 (diagnostic metric without an applicable calibrated growth band).

## Topology, descriptors, explicit release, and shutdown

File descriptors: **INCOMPLETE**; the measured window, post-release-to-shutdown, and complete descriptor lifecycle baseline comparisons must have no unexplained growth.
Descriptor lifecycle baselines: **INCOMPLETE**; the final measured FD count must not exceed the post-warm-up baseline, and post-release/post-shutdown counts must not exceed the serialized pre-runtime baseline in every independent process.

| Run | Pre-runtime FDs | Post-warm-up FDs | Final measured FDs | Post-release FDs | Post-shutdown FDs | Lifecycle status |
|---|---:|---:|---:|---:|---:|---|
| run-01 | n/a | n/a | 5.0 | 4 | 4 | incomplete |
| run-02 | n/a | n/a | 5.0 | 4 | 4 | incomplete |
| run-03 | n/a | n/a | 5.0 | 4 | 4 | incomplete |
- measured process_count: **PASS**
- measured child_process_count: **PASS**
- measured thread_count: **PASS**
- measured open_socket_count: **PASS**
- measured listening_socket_count: **PASS**

| Run | Stage | Proc. | Children | Threads | FDs | Open sockets | Listeners | RSS | PSS | Private | VM |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| run-01 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 16.89 MiB (17715200 bytes) | 14.68 MiB (15394816 bytes) | 14.53 MiB (15237120 bytes) | 220.94 MiB (231669760 bytes) |
| run-01 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.01 MiB (17838080 bytes) | 14.69 MiB (15399936 bytes) | 14.52 MiB (15228928 bytes) | 220.39 MiB (231100416 bytes) |
| run-02 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.17 MiB (18006016 bytes) | 14.78 MiB (15494144 bytes) | 14.60 MiB (15310848 bytes) | 220.94 MiB (231669760 bytes) |
| run-02 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.29 MiB (18128896 bytes) | 14.78 MiB (15498240 bytes) | 14.59 MiB (15302656 bytes) | 220.39 MiB (231100416 bytes) |
| run-03 | post-release | 1 | 0 | 4 | 4 | 0 | 0 | 17.33 MiB (18169856 bytes) | 14.98 MiB (15712256 bytes) | 14.82 MiB (15540224 bytes) | 220.94 MiB (231669760 bytes) |
| run-03 | post-shutdown | 1 | 0 | 1 | 4 | 0 | 0 | 17.45 MiB (18292736 bytes) | 14.99 MiB (15715328 bytes) | 14.81 MiB (15532032 bytes) | 220.39 MiB (231100416 bytes) |

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

All retained processes pass hard invariants, measured topology, and the retained terminal shutdown checks, but this archive is not a conclusive calibrated plateau. Its #38 comparison is inapplicable when final configuration provenance differs or is absent, and any incomplete raw/host or descriptor-lifecycle evidence must be replaced by a fresh fully recorded archive. The raw series remains available for diagnosis.
