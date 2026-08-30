# Phase 0 native-Linux calibration

- **Status:** PASS
- **Schema:** latent.phase0.calibration.v1
- **Source commit:** a724a5e35234175f1001d1983e4411296ffa6b78
- **Independent full-profile runs:** 7
- **Machine-readable aggregate:** aggregate.json

> Observational variance evidence only. This is not a production SLO, a cross-machine claim, or a shared-CI performance gate.

## Reference environment and provenance

| Field | Value |
|---|---|
| Published source commit | a724a5e35234175f1001d1983e4411296ffa6b78 |
| Published source Git tree | c06ace2ae0f503495fa5bf87710ae5fc74c7ef50 |
| Local execution commit | a724a5e35234175f1001d1983e4411296ffa6b78 |
| Local execution Git tree | c06ace2ae0f503495fa5bf87710ae5fc74c7ef50 |
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
| One-minute load observed | {'minimum': 1.08, 'maximum': 4.16} |
| Available memory observed | {'minimum': 11594227712.0, 'maximum': 12272693248.0} bytes |

Every run directory retains raw full-profile output, its concise report, and before/after host observations. Those observations record virtualization detection, allocator observation, frequency/power policy where Linux exposes it, background-load context, and the verified published/execution Git-tree provenance.

## Hard invariant status

All 7 runs passed every original Phase 0 hard invariant. No run was excluded for timing, throughput, RSS, or any other performance value. The aggregate adds no statistical tolerance to topology, capacity, containment, cleanup, or reclamation checks.

## Aggregate measurements

Rows contain all retained underlying samples where available; startup, throughput, fixed-pool P50, and per-run peak-resource rows contain one representative observation per process. MAD is median absolute deviation. CV is sample coefficient of variation.

### Activation throughput

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| at_capacity_activations_per_second — At-capacity activation throughput | activations_per_second | 7 | 7 | 625.64 | 638.00 | 670.62 | 12.06 | 2.63% | none |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | activations_per_second | 7 | 7 | 1054.98 | 1079.14 | 1096.54 | 7.43 | 1.32% | none |

### Cold and warm activation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cold_activation_elapsed_micros — Cold activation inside real executable harness | microseconds | 84 | 7 | 194 | 209 | 295 | 8 | 8.83% | none |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | microseconds | 84 | 7 | 50685 | 52147.50 | 62614 | 482 | 2.73% | none |
| warm_activation_elapsed_micros — Warm activation latency | microseconds | 280 | 7 | 101 | 132 | 285 | 27 | 29.36% | none |

### Containment and recovery

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cancellation_overshoot_micros — Cancellation interruption overshoot | microseconds | 70 | 7 | 1937 | 2267.50 | 3464 | 90 | 16.49% | none |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | microseconds | 70 | 7 | 123 | 160.50 | 250 | 22 | 18.76% | none |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | microseconds | 70 | 7 | 102 | 139 | 263 | 32.50 | 30.48% | none |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | microseconds | 70 | 7 | 141 | 159 | 242 | 17 | 16.39% | none |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | microseconds | 70 | 7 | 146 | 175 | 270 | 21.50 | 15.75% | none |
| recovery_after_trap_elapsed_micros — Recovery after trap | microseconds | 70 | 7 | 103 | 138 | 245 | 31 | 27.33% | none |
| timeout_overshoot_micros — Timeout interruption overshoot | microseconds | 70 | 7 | 0 | 693.50 | 1117 | 228 | 49.68% | none |
| trap_elapsed_micros — Trap containment latency | microseconds | 70 | 7 | 108 | 131 | 261 | 19.50 | 29.21% | run-01=167; run-04=159.50 |

### Post-invocation cleanup

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_resource_reclamation_micros — Activation-resource reclamation | microseconds | 2401 | 7 | 14 | 24 | 1477 | 6 | 125.33% | none |
| cell_disposition_micros — Cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 52 | 1 | 68.33% | none |
| component_post_return_micros — Component canonical post-return | microseconds | 2401 | 7 | 0 | 0 | 10 | 0 | 188.38% | none |
| outcome_classification_micros — Outcome classification | microseconds | 2401 | 7 | 0 | 0 | 3 | 0 | 405.16% | none |
| post_invocation_cleanup_micros — Post-invocation cleanup | microseconds | 2401 | 7 | 15 | 27 | 1481 | 7 | 113.42% | run-02=26; run-03=29; run-05=26 |
| reusable_proof_micros — Reusable-proof return | microseconds | 2401 | 7 | 0 | 0 | 2 | 0 | 593.93% | none |

### Process resources (per-run peak)

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| process_peak_file_descriptor_count — Process peak file-descriptor count | count | 7 | 7 | 5 | 5 | 5 | 0 | 0.00% | none |
| process_peak_listening_socket_count — Process peak listening sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_open_socket_count — Process peak open sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_rss_bytes — Process peak RSS | bytes | 7 | 7 | 17973248 | 18087936 | 18178048 | 53248 | 0.39% | none |
| process_peak_thread_count — Process peak thread count | count | 7 | 7 | 4 | 4 | 4 | 0 | 0.00% | none |
| process_peak_virtual_memory_bytes — Process peak virtual memory | bytes | 7 | 7 | 231796736 | 231800832 | 231936000 | 4096 | 0.03% | run-03=231931904; run-07=231936000 |

### Queueing and release

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | microseconds | 2401 | 7 | 0 | 4 | 4840 | 2 | 172.03% | none |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 52 | 1 | 68.33% | none |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | microseconds | 602 | 7 | 1129 | 2393.50 | 4840 | 223.50 | 33.28% | none |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | microseconds | 7 | 7 | 32 | 35 | 43 | 3 | 12.36% | none |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |

### Startup and preparation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| capsule_validation_and_load_micros — Capsule validation and component load | microseconds | 7 | 7 | 61 | 75 | 81 | 6 | 11.60% | none |
| component_preparation_micros — Component preparation | microseconds | 7 | 7 | 48493 | 48674 | 49308 | 181 | 0.59% | none |
| prepared_component_release_micros — Prepared-component release | microseconds | 7 | 7 | 62 | 66 | 75 | 1 | 6.18% | run-07=75 |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | microseconds | 7 | 7 | 55300 | 55632 | 56207 | 133 | 0.53% | none |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | microseconds | 7 | 7 | 3854 | 4040 | 4251 | 94 | 3.20% | none |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | microseconds | 7 | 7 | 144 | 154 | 182 | 5 | 7.91% | run-04=182 |

## Environmental noise and outliers

Outliers use per-run representative values and a robust z-score above 3.5, or any deviation from a zero-MAD run-level median. Flags remain in the aggregate and raw archive; they prompt investigation or rerun and never permit discarding a run.

| Metric | Flagged runs |
|---|---|
| post_invocation_cleanup_micros | run-02=26 (deviates from a zero-MAD run-level median); run-03=29 (deviates from a zero-MAD run-level median); run-05=26 (deviates from a zero-MAD run-level median) |
| prepared_component_release_micros | run-07=75 (run-level robust z-score exceeds 3.5) |
| process_peak_virtual_memory_bytes | run-03=231931904 (run-level robust z-score exceeds 3.5); run-07=231936000 (run-level robust z-score exceeds 3.5) |
| trap_elapsed_micros | run-01=167 (run-level robust z-score exceeds 3.5); run-04=159.50 (run-level robust z-score exceeds 3.5) |
| wasmtime_engine_construction_micros | run-04=182 (run-level robust z-score exceeds 3.5) |

## Phase 1 advisory comparison bands

The bands are like-for-like native-Linux regression-detection aids, not SLOs, release promises, or cross-machine claims. Candidates need at least seven comparable full-profile processes and all hard invariants must pass.

| Metric | Direction | Reference run median | Advisory noise band | Candidate regression rule |
|---|---|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | higher is worse | 4 | 10 | candidate median > reference median + advisory_noise_band |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | higher is worse | 2391.50 | 239.15 | candidate median > reference median + advisory_noise_band |
| activation_resource_reclamation_micros — Activation-resource reclamation | higher is worse | 24 | 10 | candidate median > reference median + advisory_noise_band |
| at_capacity_activations_per_second — At-capacity activation throughput | lower is worse | 638.00 | 95.70 | candidate median < reference median - advisory_noise_band |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | lower is worse | 1079.14 | 161.87 | candidate median < reference median - advisory_noise_band |
| cancellation_overshoot_micros — Cancellation interruption overshoot | higher is worse | 2256.50 | 225.65 | candidate median > reference median + advisory_noise_band |
| capsule_validation_and_load_micros — Capsule validation and component load | higher is worse | 75 | 18 | candidate median > reference median + advisory_noise_band |
| cell_disposition_micros — Cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| cold_activation_elapsed_micros — Cold activation inside real executable harness | higher is worse | 210 | 21 | candidate median > reference median + advisory_noise_band |
| component_post_return_micros — Component canonical post-return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| component_preparation_micros — Component preparation | higher is worse | 48674 | 4867.40 | candidate median > reference median + advisory_noise_band |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | higher is worse | 35 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| outcome_classification_micros — Outcome classification | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| post_invocation_cleanup_micros — Post-invocation cleanup | higher is worse | 27 | 10 | candidate median > reference median + advisory_noise_band |
| prepared_component_release_micros — Prepared-component release | higher is worse | 66 | 10 | candidate median > reference median + advisory_noise_band |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | higher is worse | 52146.50 | 5214.65 | candidate median > reference median + advisory_noise_band |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | higher is worse | 55632 | 5563.20 | candidate median > reference median + advisory_noise_band |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | higher is worse | 4040 | 404 | candidate median > reference median + advisory_noise_band |
| process_peak_rss_bytes — Process peak RSS | higher is worse | 18087936 | 1808793.60 | candidate median > reference median + advisory_noise_band |
| process_peak_virtual_memory_bytes — Process peak virtual memory | higher is worse | 231800832 | 23180083.20 | candidate median > reference median + advisory_noise_band |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | higher is worse | 166 | 21 | candidate median > reference median + advisory_noise_band |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | higher is worse | 136.50 | 34.50 | candidate median > reference median + advisory_noise_band |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | higher is worse | 163.50 | 21 | candidate median > reference median + advisory_noise_band |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | higher is worse | 174.50 | 21 | candidate median > reference median + advisory_noise_band |
| recovery_after_trap_elapsed_micros — Recovery after trap | higher is worse | 144.50 | 61.50 | candidate median > reference median + advisory_noise_band |
| reusable_proof_micros — Reusable-proof return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| timeout_overshoot_micros — Timeout interruption overshoot | higher is worse | 706.50 | 148.50 | candidate median > reference median + advisory_noise_band |
| trap_elapsed_micros — Trap containment latency | higher is worse | 131 | 13.50 | candidate median > reference median + advisory_noise_band |
| warm_activation_elapsed_micros — Warm activation latency | higher is worse | 134 | 13.40 | candidate median > reference median + advisory_noise_band |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | higher is worse | 154 | 15.40 | candidate median > reference median + advisory_noise_band |

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
