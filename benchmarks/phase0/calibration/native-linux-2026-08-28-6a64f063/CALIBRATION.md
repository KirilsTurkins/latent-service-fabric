# Phase 0 native-Linux calibration

- **Status:** PASS
- **Schema:** latent.phase0.calibration.v1
- **Source commit:** 6a64f0630cee9afa080d33f376aabadac724fa72
- **Independent full-profile runs:** 7
- **Machine-readable aggregate:** aggregate.json

> Observational variance evidence only. This is not a production SLO, a cross-machine claim, or a shared-CI performance gate.

## Reference environment and provenance

| Field | Value |
|---|---|
| Published source commit | 6a64f0630cee9afa080d33f376aabadac724fa72 |
| Published source Git tree | d27ff38ebbd891c5be949f54a0047522ed893d20 |
| Local execution commit | f5829873fb1086806fdaf2254617731e75af51ff |
| Local execution Git tree | d27ff38ebbd891c5be949f54a0047522ed893d20 |
| Published/execution tree identity verified | True |
| CPU | AMD Ryzen 3 3200G with Radeon Vega Graphics |
| Logical CPUs | 4 |
| Memory | 16699981824 bytes |
| Kernel | Linux 7.1.5-201.fc44.x86_64 #1 SMP PREEMPT_DYNAMIC Tue Jul 28 14:16:30 UTC 2026 x86_64 GNU/Linux |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14)<br>binary: rustc<br>commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452<br>commit-date: 2026-07-14<br>host: x86_64-unknown-linux-gnu<br>release: 1.97.1<br>LLVM version: 22.1.6 |
| Cargo | cargo 1.97.1 (c980f4866 2026-06-30) |
| Wasmtime | 47.0.3 (workspace pin) |
| Target / build profile | x86_64-unknown-linux-gnu / release |
| Fixture digest | sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b |
| Native-Linux reference | True |
| Virtualization | {'systemd_detect_virt': 'none', 'systemd_detect_virt_container': 'none', 'systemd_detect_virt_vm': 'none', 'wsl_detected': False} |
| Allocator observation | {'ld_preload': 'unset', 'malloc_conf': 'unset', 'observation': 'When no source global allocator is found and LD_PRELOAD is unset, Rust uses its standard allocator backed by the platform allocator.', 'source_global_allocator_lookup': 'completed', 'source_global_allocator_matches': []} |
| CPU frequency/power policy | {'cpus_with_cpufreq_sysfs': 0, 'current_frequency_khz_range': None, 'notes': 'Read-only Linux cpufreq observations. The command does not pin governors or frequencies.', 'observed': {}} |
| One-minute load observed | {'minimum': 2.8, 'maximum': 10.34} |
| Available memory observed | {'minimum': 10428973056.0, 'maximum': 10769154048.0} bytes |

Every run directory retains raw full-profile output, its concise report, and before/after host observations. Those observations record virtualization detection, allocator observation, frequency/power policy where Linux exposes it, background-load context, and the verified published/execution Git-tree provenance.

## Hard invariant status

All 7 runs passed every original Phase 0 hard invariant. No run was excluded for timing, throughput, RSS, or any other performance value. The aggregate adds no statistical tolerance to topology, capacity, containment, cleanup, or reclamation checks.

## Aggregate measurements

Rows contain all retained underlying samples where available; startup, throughput, fixed-pool P50, and per-run peak-resource rows contain one representative observation per process. MAD is median absolute deviation. CV is sample coefficient of variation.

### Activation throughput

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| at_capacity_activations_per_second — At-capacity activation throughput | activations_per_second | 7 | 7 | 647.46 | 668.64 | 676.85 | 2.27 | 1.48% | run-07=647.46 |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | activations_per_second | 7 | 7 | 1019.01 | 1079.74 | 1116.30 | 6.69 | 2.74% | run-01=1019.01; run-02=1116.30 |

### Cold and warm activation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cold_activation_elapsed_micros — Cold activation inside real executable harness | microseconds | 84 | 7 | 197 | 213.50 | 292 | 6 | 8.49% | run-04=221.50 |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | microseconds | 84 | 7 | 50903 | 52029 | 56825 | 620 | 1.99% | none |
| warm_activation_elapsed_micros — Warm activation latency | microseconds | 280 | 7 | 100 | 154.50 | 278 | 39.50 | 28.72% | none |

### Containment and recovery

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cancellation_overshoot_micros — Cancellation interruption overshoot | microseconds | 70 | 7 | 1474 | 2362 | 3515 | 78 | 13.01% | none |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | microseconds | 70 | 7 | 127 | 181 | 265 | 22.50 | 16.92% | none |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | microseconds | 70 | 7 | 103 | 129.50 | 253 | 24.50 | 28.20% | run-06=187.50 |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | microseconds | 70 | 7 | 140 | 177 | 274 | 28 | 18.02% | none |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | microseconds | 70 | 7 | 145 | 186.50 | 284 | 27.50 | 17.90% | none |
| recovery_after_trap_elapsed_micros — Recovery after trap | microseconds | 70 | 7 | 106 | 133.50 | 262 | 24.50 | 28.06% | run-02=182; run-06=197 |
| timeout_overshoot_micros — Timeout interruption overshoot | microseconds | 70 | 7 | 0 | 626.50 | 3043 | 281 | 68.77% | none |
| trap_elapsed_micros — Trap containment latency | microseconds | 70 | 7 | 110 | 138.50 | 270 | 24.50 | 27.92% | none |

### Post-invocation cleanup

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_resource_reclamation_micros — Activation-resource reclamation | microseconds | 2401 | 7 | 14 | 25 | 881 | 6 | 104.89% | none |
| cell_disposition_micros — Cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 23 | 1 | 56.32% | none |
| component_post_return_micros — Component canonical post-return | microseconds | 2401 | 7 | 0 | 0 | 17 | 0 | 180.46% | none |
| outcome_classification_micros — Outcome classification | microseconds | 2401 | 7 | 0 | 0 | 2 | 0 | 405.62% | none |
| post_invocation_cleanup_micros — Post-invocation cleanup | microseconds | 2401 | 7 | 15 | 28 | 890 | 7 | 96.37% | none |
| reusable_proof_micros — Reusable-proof return | microseconds | 2401 | 7 | 0 | 0 | 2 | 0 | 492.37% | none |

### Process resources (per-run peak)

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| process_peak_file_descriptor_count — Process peak file-descriptor count | count | 7 | 7 | 5 | 5 | 5 | 0 | 0.00% | none |
| process_peak_listening_socket_count — Process peak listening sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_open_socket_count — Process peak open sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_rss_bytes — Process peak RSS | bytes | 7 | 7 | 17973248 | 18194432 | 18374656 | 114688 | 0.77% | none |
| process_peak_thread_count — Process peak thread count | count | 7 | 7 | 4 | 4 | 4 | 0 | 0.00% | none |
| process_peak_virtual_memory_bytes — Process peak virtual memory | bytes | 7 | 7 | 231780352 | 231780352 | 231788544 | 0 | 0.00% | run-02=231784448; run-04=231788544; run-05=231784448 |

### Queueing and release

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | microseconds | 2401 | 7 | 0 | 4 | 4327 | 2 | 171.71% | run-01=5; run-02=5; run-06=5 |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 23 | 1 | 56.32% | none |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | microseconds | 596 | 7 | 1162 | 2406.50 | 4327 | 282 | 32.65% | none |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | microseconds | 7 | 7 | 27 | 35 | 42 | 1 | 12.74% | run-03=42; run-06=27 |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |

### Startup and preparation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| capsule_validation_and_load_micros — Capsule validation and component load | microseconds | 7 | 7 | 58 | 63 | 76 | 5 | 11.91% | none |
| component_preparation_micros — Component preparation | microseconds | 7 | 7 | 48103 | 49119 | 52375 | 262 | 2.92% | run-06=52375 |
| prepared_component_release_micros — Prepared-component release | microseconds | 7 | 7 | 75 | 79 | 111 | 2 | 15.06% | run-05=111 |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | microseconds | 7 | 7 | 54548 | 55854 | 59676 | 412 | 2.97% | run-06=59676 |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | microseconds | 7 | 7 | 3841 | 3872 | 4131 | 31 | 3.15% | run-03=4110; run-05=4131 |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | microseconds | 7 | 7 | 141 | 161 | 174 | 8 | 8.11% | none |

## Environmental noise and outliers

Outliers use per-run representative values and a robust z-score above 3.5, or any deviation from a zero-MAD run-level median. Flags remain in the aggregate and raw archive; they prompt investigation or rerun and never permit discarding a run.

| Metric | Flagged runs |
|---|---|
| activation_acquire_or_queue_wait_micros | run-01=5 (deviates from a zero-MAD run-level median); run-02=5 (deviates from a zero-MAD run-level median); run-06=5 (deviates from a zero-MAD run-level median) |
| at_capacity_activations_per_second | run-07=647.46 (run-level robust z-score exceeds 3.5) |
| bounded_queue_saturation_activations_per_second | run-01=1019.01 (run-level robust z-score exceeds 3.5); run-02=1116.30 (run-level robust z-score exceeds 3.5) |
| cold_activation_elapsed_micros | run-04=221.50 (run-level robust z-score exceeds 3.5) |
| component_preparation_micros | run-06=52375 (run-level robust z-score exceeds 3.5) |
| fixed_pool_queued_wait_p50_micros | run-03=42 (run-level robust z-score exceeds 3.5); run-06=27 (run-level robust z-score exceeds 3.5) |
| prepared_component_release_micros | run-05=111 (run-level robust z-score exceeds 3.5) |
| process_launch_to_ready_to_invoke_micros | run-06=59676 (run-level robust z-score exceeds 3.5) |
| process_launch_to_runtime_ready_micros | run-03=4110 (run-level robust z-score exceeds 3.5); run-05=4131 (run-level robust z-score exceeds 3.5) |
| process_peak_virtual_memory_bytes | run-02=231784448 (deviates from a zero-MAD run-level median); run-04=231788544 (deviates from a zero-MAD run-level median); run-05=231784448 (deviates from a zero-MAD run-level median) |
| recovery_after_domain_error_elapsed_micros | run-06=187.50 (run-level robust z-score exceeds 3.5) |
| recovery_after_trap_elapsed_micros | run-02=182 (run-level robust z-score exceeds 3.5); run-06=197 (run-level robust z-score exceeds 3.5) |

## Phase 1 advisory comparison bands

The bands are like-for-like native-Linux regression-detection aids, not SLOs, release promises, or cross-machine claims. Candidates need at least seven comparable full-profile processes and all hard invariants must pass.

| Metric | Direction | Reference run median | Advisory noise band | Candidate regression rule |
|---|---|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | higher is worse | 4 | 10 | candidate median > reference median + advisory_noise_band |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | higher is worse | 2400 | 240 | candidate median > reference median + advisory_noise_band |
| activation_resource_reclamation_micros — Activation-resource reclamation | higher is worse | 25 | 10 | candidate median > reference median + advisory_noise_band |
| at_capacity_activations_per_second — At-capacity activation throughput | lower is worse | 668.64 | 100.30 | candidate median < reference median - advisory_noise_band |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | lower is worse | 1079.74 | 161.96 | candidate median < reference median - advisory_noise_band |
| cancellation_overshoot_micros — Cancellation interruption overshoot | higher is worse | 2359 | 235.90 | candidate median > reference median + advisory_noise_band |
| capsule_validation_and_load_micros — Capsule validation and component load | higher is worse | 63 | 15 | candidate median > reference median + advisory_noise_band |
| cell_disposition_micros — Cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| cold_activation_elapsed_micros — Cold activation inside real executable harness | higher is worse | 213.50 | 21.35 | candidate median > reference median + advisory_noise_band |
| component_post_return_micros — Component canonical post-return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| component_preparation_micros — Component preparation | higher is worse | 49119 | 4911.90 | candidate median > reference median + advisory_noise_band |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | higher is worse | 35 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| outcome_classification_micros — Outcome classification | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| post_invocation_cleanup_micros — Post-invocation cleanup | higher is worse | 28 | 10 | candidate median > reference median + advisory_noise_band |
| prepared_component_release_micros — Prepared-component release | higher is worse | 79 | 10 | candidate median > reference median + advisory_noise_band |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | higher is worse | 51989.50 | 5198.95 | candidate median > reference median + advisory_noise_band |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | higher is worse | 55854 | 5585.40 | candidate median > reference median + advisory_noise_band |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | higher is worse | 3872 | 387.20 | candidate median > reference median + advisory_noise_band |
| process_peak_rss_bytes — Process peak RSS | higher is worse | 18194432 | 1819443.20 | candidate median > reference median + advisory_noise_band |
| process_peak_virtual_memory_bytes — Process peak virtual memory | higher is worse | 231780352 | 23178035.20 | candidate median > reference median + advisory_noise_band |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | higher is worse | 182.50 | 22.50 | candidate median > reference median + advisory_noise_band |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | higher is worse | 124.50 | 12.45 | candidate median > reference median + advisory_noise_band |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | higher is worse | 172.50 | 27 | candidate median > reference median + advisory_noise_band |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | higher is worse | 182 | 25.50 | candidate median > reference median + advisory_noise_band |
| recovery_after_trap_elapsed_micros — Recovery after trap | higher is worse | 124 | 12.40 | candidate median > reference median + advisory_noise_band |
| reusable_proof_micros — Reusable-proof return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| timeout_overshoot_micros — Timeout interruption overshoot | higher is worse | 621 | 148.50 | candidate median > reference median + advisory_noise_band |
| trap_elapsed_micros — Trap containment latency | higher is worse | 148.50 | 84 | candidate median > reference median + advisory_noise_band |
| warm_activation_elapsed_micros — Warm activation latency | higher is worse | 139.50 | 42 | candidate median > reference median + advisory_noise_band |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | higher is worse | 161 | 24 | candidate median > reference median + advisory_noise_band |

An inside-band candidate with at least seven valid comparable runs, a stable environment, all hard invariants passing, and no material run-level outlier is terminally **no detectable regression** (or statistically indistinguishable). Insufficient samples, environment instability, material outliers, or a failed invariant are inconclusive and must be rerun after the invalid condition is resolved. A deterioration outside a band is a regression candidate that requires a second comparable set; repeated outside-band deterioration confirms the regression.

Shared hosted CI must never fail on these microbenchmark bands; it may run the deterministic Phase 0 correctness smoke profile only.

## Raw run archive

| Run | Raw full-profile output | Per-run report | Host observations | Exit status |
|---|---|---|---|---|
| run-01 | runs/run-01/raw-results.json | runs/run-01/BASELINE.md | runs/run-01/host-before.json, runs/run-01/host-after.json | runs/run-01/execution-status.json |
| run-02 | runs/run-02/raw-results.json | runs/run-02/BASELINE.md | runs/run-02/host-before.json, runs/run-02/host-after.json | runs/run-02/execution-status.json |
| run-03 | runs/run-03/raw-results.json | runs/run-03/BASELINE.md | runs/run-03/host-before.json, runs/run-03/host-after.json | runs/run-03/execution-status.json |
| run-04 | runs/run-04/raw-results.json | runs/run-04/BASELINE.md | runs/run-04/host-before.json, runs/run-04/host-after.json | runs/run-04/execution-status.json |
| run-05 | runs/run-05/raw-results.json | runs/run-05/BASELINE.md | runs/run-05/host-before.json, runs/run-05/host-after.json | runs/run-05/execution-status.json |
| run-06 | runs/run-06/raw-results.json | runs/run-06/BASELINE.md | runs/run-06/host-before.json, runs/run-06/host-after.json | runs/run-06/execution-status.json |
| run-07 | runs/run-07/raw-results.json | runs/run-07/BASELINE.md | runs/run-07/host-before.json, runs/run-07/host-after.json | runs/run-07/execution-status.json |

## Limitations

- The workload is the Phase 0 spike, not a productionized multi-service or cluster workload.
- CPU frequency and background load are observed where available, not controlled by this command.
- This calibration does not establish dormant-service density, long-duration soak behavior, remote calls, or production capacity.
- Phase 1 must report deltas against this evidence instead of replacing the reference after productionization.
