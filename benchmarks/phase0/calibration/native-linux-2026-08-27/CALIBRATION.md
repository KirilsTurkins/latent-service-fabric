# Phase 0 native-Linux calibration

- **Status:** PASS
- **Schema:** latent.phase0.calibration.v1
- **Source commit:** 75c97d315157f3bb2187c9ae6a02b44662faf68f
- **Independent full-profile runs:** 7
- **Machine-readable aggregate:** aggregate.json

> Observational variance evidence only. This is not a production SLO, a cross-machine claim, or a shared-CI performance gate.

## Reference environment and provenance

| Field | Value |
|---|---|
| CPU | AMD Ryzen 3 3200G with Radeon Vega Graphics |
| Logical CPUs | 4 |
| Memory | 16699981824 bytes |
| Kernel | Linux 7.1.5-201.fc44.x86_64 #1 SMP PREEMPT_DYNAMIC Tue Jul 28 14:16:30 UTC 2026 x86_64 GNU/Linux |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14)<br>binary: rustc<br>commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452<br>commit-date: 2026-07-14<br>host: x86_64-unknown-linux-gnu<br>release: 1.97.1<br>LLVM version: 22.1.6 |
| Cargo | cargo 1.97.1 (c980f4866 2026-06-30) |
| Wasmtime | 47.0.3 (workspace pin) |
| Target / build profile | x86_64-unknown-linux-gnu / release |
| Fixture digest | sha256:3c1ef992432eddb0e84741aa0681a0a3af06635b7c24f4b96d507dd2a90cbbdd |
| Native-Linux reference | True |
| Virtualization | {'systemd_detect_virt': 'none', 'systemd_detect_virt_container': 'none', 'systemd_detect_virt_vm': 'none', 'wsl_detected': False} |
| Allocator observation | {'ld_preload': 'unset', 'malloc_conf': 'unset', 'observation': 'When no source global allocator is found and LD_PRELOAD is unset, Rust uses its standard allocator backed by the platform allocator.', 'source_global_allocator_lookup': 'completed', 'source_global_allocator_matches': []} |
| CPU frequency/power policy | {'cpus_with_cpufreq_sysfs': 0, 'current_frequency_khz_range': None, 'notes': 'Read-only Linux cpufreq observations. The command does not pin governors or frequencies.', 'observed': {}} |
| One-minute load observed | {'minimum': 0.91, 'maximum': 4.8} |
| Available memory observed | {'minimum': 10386440192.0, 'maximum': 11092848640.0} bytes |

Every run directory retains raw full-profile output, its concise report, and before/after host observations. Those observations record virtualization detection, allocator observation, frequency/power policy where Linux exposes it, and background-load context.

## Hard invariant status

All 7 runs passed every original Phase 0 hard invariant. No run was excluded for timing, throughput, RSS, or any other performance value. The aggregate adds no statistical tolerance to topology, capacity, containment, cleanup, or reclamation checks.

## Aggregate measurements

Rows contain all retained underlying samples where available; startup, throughput, fixed-pool P50, and per-run peak-resource rows contain one representative observation per process. MAD is median absolute deviation. CV is sample coefficient of variation.

### Activation throughput

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| at_capacity_activations_per_second — At-capacity activation throughput | activations_per_second | 7 | 7 | 637.27 | 665.01 | 672.87 | 7.86 | 1.95% | none |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | activations_per_second | 7 | 7 | 1024.78 | 1085.07 | 1124.43 | 6.24 | 2.72% | run-04=1124.43; run-05=1024.78 |

### Cold and warm activation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cold_activation_elapsed_micros — Cold activation inside real executable harness | microseconds | 84 | 7 | 198 | 212.50 | 385 | 8 | 11.81% | none |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | microseconds | 84 | 7 | 50122 | 51272 | 58883 | 566.50 | 2.30% | none |
| warm_activation_elapsed_micros — Warm activation latency | microseconds | 280 | 7 | 98 | 144.50 | 312 | 38.50 | 30.67% | none |

### Containment and recovery

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cancellation_overshoot_micros — Cancellation interruption overshoot | microseconds | 70 | 7 | 1379 | 2378.50 | 3323 | 70 | 12.53% | run-02=2243 |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | microseconds | 70 | 7 | 122 | 160.50 | 261 | 20.50 | 18.32% | none |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | microseconds | 70 | 7 | 100 | 118.50 | 234 | 16 | 28.87% | run-04=166.50; run-06=106 |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | microseconds | 70 | 7 | 141 | 163 | 265 | 18 | 16.01% | none |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | microseconds | 70 | 7 | 146 | 169.50 | 276 | 20 | 18.57% | none |
| recovery_after_trap_elapsed_micros — Recovery after trap | microseconds | 70 | 7 | 103 | 133.50 | 274 | 27.50 | 29.30% | none |
| timeout_overshoot_micros — Timeout interruption overshoot | microseconds | 70 | 7 | 102 | 552.50 | 1129 | 202 | 45.91% | none |
| trap_elapsed_micros — Trap containment latency | microseconds | 70 | 7 | 107 | 126.50 | 265 | 16.50 | 31.02% | run-06=181 |

### Post-invocation cleanup

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_resource_reclamation_micros — Activation-resource reclamation | microseconds | 2401 | 7 | 15 | 24 | 459 | 6 | 82.37% | run-02=26; run-05=26; run-07=22 |
| cell_disposition_micros — Cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 29 | 1 | 56.43% | none |
| component_post_return_micros — Component canonical post-return | microseconds | 2401 | 7 | 0 | 0 | 72 | 0 | 311.33% | none |
| outcome_classification_micros — Outcome classification | microseconds | 2401 | 7 | 0 | 0 | 13 | 0 | 508.38% | none |
| post_invocation_cleanup_micros — Post-invocation cleanup | microseconds | 2401 | 7 | 17 | 28 | 473 | 7 | 76.09% | none |
| reusable_proof_micros — Reusable-proof return | microseconds | 2401 | 7 | 0 | 0 | 5 | 0 | 504.64% | none |

### Process resources (per-run peak)

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| process_peak_file_descriptor_count — Process peak file-descriptor count | count | 7 | 7 | 5 | 5 | 5 | 0 | 0.00% | none |
| process_peak_listening_socket_count — Process peak listening sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_open_socket_count — Process peak open sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_rss_bytes — Process peak RSS | bytes | 7 | 7 | 17412096 | 17625088 | 17825792 | 139264 | 0.86% | none |
| process_peak_thread_count — Process peak thread count | count | 7 | 7 | 4 | 4 | 4 | 0 | 0.00% | none |
| process_peak_virtual_memory_bytes — Process peak virtual memory | bytes | 7 | 7 | 231284736 | 231297024 | 231424000 | 4096 | 0.02% | run-04=231424000 |

### Queueing and release

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | microseconds | 2401 | 7 | 0 | 4 | 4740 | 2 | 172.05% | none |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 29 | 1 | 56.43% | none |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | microseconds | 610 | 7 | 1148 | 2383 | 4740 | 410 | 33.11% | none |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | microseconds | 7 | 7 | 26 | 30 | 44 | 3 | 19.30% | none |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |

### Startup and preparation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| capsule_validation_and_load_micros — Capsule validation and component load | microseconds | 7 | 7 | 63 | 77 | 92 | 6 | 12.11% | none |
| component_preparation_micros — Component preparation | microseconds | 7 | 7 | 47333 | 47892 | 48228 | 211 | 0.61% | none |
| prepared_component_release_micros — Prepared-component release | microseconds | 7 | 7 | 67 | 77 | 101 | 5 | 14.80% | none |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | microseconds | 7 | 7 | 54081 | 54734 | 54857 | 123 | 0.59% | run-06=54081 |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | microseconds | 7 | 7 | 3693 | 3934 | 4090 | 156 | 3.64% | none |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | microseconds | 7 | 7 | 161 | 176 | 187 | 9 | 5.44% | none |

## Environmental noise and outliers

Outliers use per-run representative values and a robust z-score above 3.5, or any deviation from a zero-MAD run-level median. Flags remain in the aggregate and raw archive; they prompt investigation or rerun and never permit discarding a run.

| Metric | Flagged runs |
|---|---|
| activation_resource_reclamation_micros | run-02=26 (deviates from a zero-MAD run-level median); run-05=26 (deviates from a zero-MAD run-level median); run-07=22 (deviates from a zero-MAD run-level median) |
| bounded_queue_saturation_activations_per_second | run-04=1124.43 (run-level robust z-score exceeds 3.5); run-05=1024.78 (run-level robust z-score exceeds 3.5) |
| cancellation_overshoot_micros | run-02=2243 (run-level robust z-score exceeds 3.5) |
| process_launch_to_ready_to_invoke_micros | run-06=54081 (run-level robust z-score exceeds 3.5) |
| process_peak_virtual_memory_bytes | run-04=231424000 (run-level robust z-score exceeds 3.5) |
| recovery_after_domain_error_elapsed_micros | run-04=166.50 (run-level robust z-score exceeds 3.5); run-06=106 (run-level robust z-score exceeds 3.5) |
| trap_elapsed_micros | run-06=181 (run-level robust z-score exceeds 3.5) |

## Phase 1 advisory comparison bands

The bands are like-for-like native-Linux regression-detection aids, not SLOs, release promises, or cross-machine claims. Candidates need at least seven comparable full-profile processes and all hard invariants must pass.

| Metric | Direction | Reference run median | Advisory noise band | Candidate regression rule |
|---|---|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | higher is worse | 4 | 10 | candidate median > reference median + advisory_noise_band |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | higher is worse | 2384.50 | 238.45 | candidate median > reference median + advisory_noise_band |
| activation_resource_reclamation_micros — Activation-resource reclamation | higher is worse | 24 | 10 | candidate median > reference median + advisory_noise_band |
| at_capacity_activations_per_second — At-capacity activation throughput | lower is worse | 665.01 | 99.75 | candidate median < reference median - advisory_noise_band |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | lower is worse | 1085.07 | 162.76 | candidate median < reference median - advisory_noise_band |
| cancellation_overshoot_micros — Cancellation interruption overshoot | higher is worse | 2380 | 238 | candidate median > reference median + advisory_noise_band |
| capsule_validation_and_load_micros — Capsule validation and component load | higher is worse | 77 | 18 | candidate median > reference median + advisory_noise_band |
| cell_disposition_micros — Cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| cold_activation_elapsed_micros — Cold activation inside real executable harness | higher is worse | 214 | 21.40 | candidate median > reference median + advisory_noise_band |
| component_post_return_micros — Component canonical post-return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| component_preparation_micros — Component preparation | higher is worse | 47892 | 4789.20 | candidate median > reference median + advisory_noise_band |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | higher is worse | 30 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| outcome_classification_micros — Outcome classification | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| post_invocation_cleanup_micros — Post-invocation cleanup | higher is worse | 28 | 10 | candidate median > reference median + advisory_noise_band |
| prepared_component_release_micros — Prepared-component release | higher is worse | 77 | 15 | candidate median > reference median + advisory_noise_band |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | higher is worse | 51314 | 5131.40 | candidate median > reference median + advisory_noise_band |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | higher is worse | 54734 | 5473.40 | candidate median > reference median + advisory_noise_band |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | higher is worse | 3934 | 468 | candidate median > reference median + advisory_noise_band |
| process_peak_rss_bytes — Process peak RSS | higher is worse | 17625088 | 1762508.80 | candidate median > reference median + advisory_noise_band |
| process_peak_virtual_memory_bytes — Process peak virtual memory | higher is worse | 231297024 | 23129702.40 | candidate median > reference median + advisory_noise_band |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | higher is worse | 169.50 | 19.50 | candidate median > reference median + advisory_noise_band |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | higher is worse | 123.50 | 12.35 | candidate median > reference median + advisory_noise_band |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | higher is worse | 171.50 | 48 | candidate median > reference median + advisory_noise_band |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | higher is worse | 173.50 | 46.50 | candidate median > reference median + advisory_noise_band |
| recovery_after_trap_elapsed_micros — Recovery after trap | higher is worse | 128 | 34.50 | candidate median > reference median + advisory_noise_band |
| reusable_proof_micros — Reusable-proof return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| timeout_overshoot_micros — Timeout interruption overshoot | higher is worse | 618.50 | 271.50 | candidate median > reference median + advisory_noise_band |
| trap_elapsed_micros — Trap containment latency | higher is worse | 126 | 16.50 | candidate median > reference median + advisory_noise_band |
| warm_activation_elapsed_micros — Warm activation latency | higher is worse | 147 | 19.50 | candidate median > reference median + advisory_noise_band |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | higher is worse | 176 | 27 | candidate median > reference median + advisory_noise_band |

Results inside an advisory band, results with a material run-level outlier or background-load disturbance, and results with fewer than seven comparable runs are inconclusive and must be rerun. A deterioration outside a band is a regression candidate that requires a second comparable set before confirmation.

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
