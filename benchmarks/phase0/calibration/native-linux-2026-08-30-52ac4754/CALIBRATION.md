# Phase 0 native-Linux calibration

- **Status:** PASS
- **Schema:** latent.phase0.calibration.v2
- **Source commit:** 52ac47542a05c0a1263f78a14c04a5c2e6b761f3
- **Independent full-profile runs:** 7
- **Machine-readable aggregate:** aggregate.json

> Observational variance evidence only. This is not a production SLO, a cross-machine claim, or a shared-CI performance gate.

## Reference environment and provenance

| Field | Value |
|---|---|
| Published source commit | 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 |
| Published source Git tree | cac3ececdbd0b5734691c30c0283fccff169a5f5 |
| Durable published source ref | refs/heads/fix/phase0-gate-validation |
| Resolved durable ref head | 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 |
| Published commit reachable from ref | True |
| Local execution commit | 52ac47542a05c0a1263f78a14c04a5c2e6b761f3 |
| Local execution Git tree | cac3ececdbd0b5734691c30c0283fccff169a5f5 |
| Execution HEAD equals published commit | True |
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
| One-minute load observed | {'minimum': 1.05, 'maximum': 5.2} |
| Available memory observed | {'minimum': 9124605952.0, 'maximum': 9306566656.0} bytes |

Every run directory retains raw full-profile output, its concise report, and before/after host observations. Those observations record virtualization detection, allocator observation, frequency/power policy where Linux exposes it, background-load context, and the verified published/execution Git-tree provenance.

## Hard invariant status

All 7 runs passed every original Phase 0 hard invariant. No run was excluded for timing, throughput, RSS, or any other performance value. The aggregate adds no statistical tolerance to topology, capacity, containment, cleanup, or reclamation checks.

## Aggregate measurements

Rows contain all retained underlying samples where available; startup, throughput, fixed-pool P50, and per-run peak-resource rows contain one representative observation per process. MAD is median absolute deviation. CV is sample coefficient of variation.

### Activation throughput

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| at_capacity_activations_per_second — At-capacity activation throughput | activations_per_second | 7 | 7 | 549.58 | 626.53 | 643.82 | 8.02 | 5.10% | run-07=549.58 |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | activations_per_second | 7 | 7 | 952.53 | 1053.22 | 1071.11 | 17.89 | 4.85% | run-07=952.53 |

### Cold and warm activation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cold_activation_elapsed_micros — Cold activation inside real executable harness | microseconds | 84 | 7 | 198 | 220 | 370 | 13.50 | 15.80% | none |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | microseconds | 84 | 7 | 51717 | 53044.50 | 66153 | 673.50 | 4.16% | run-02=55865.50 |
| warm_activation_elapsed_micros — Warm activation latency | microseconds | 280 | 7 | 101 | 153.50 | 330 | 40.50 | 32.31% | run-06=170 |

### Containment and recovery

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| cancellation_overshoot_micros — Cancellation interruption overshoot | microseconds | 70 | 7 | 1782 | 2269.50 | 5328 | 177.50 | 24.50% | none |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | microseconds | 70 | 7 | 129 | 185 | 300 | 24.50 | 24.33% | run-03=169.50 |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | microseconds | 70 | 7 | 105 | 177 | 308 | 38.50 | 31.01% | run-04=114.50 |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | microseconds | 70 | 7 | 143 | 179.50 | 311 | 27.50 | 23.74% | none |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | microseconds | 70 | 7 | 147 | 189.50 | 342 | 20.50 | 20.71% | none |
| recovery_after_trap_elapsed_micros — Recovery after trap | microseconds | 70 | 7 | 107 | 142.50 | 333 | 33.50 | 31.94% | none |
| timeout_overshoot_micros — Timeout interruption overshoot | microseconds | 70 | 7 | 0 | 637 | 1490 | 252 | 55.06% | none |
| trap_elapsed_micros — Trap containment latency | microseconds | 70 | 7 | 111 | 139 | 308 | 26 | 33.18% | none |

### Post-invocation cleanup

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_resource_reclamation_micros — Activation-resource reclamation | microseconds | 2401 | 7 | 14 | 26 | 1406 | 7 | 115.38% | run-01=23; run-02=26; run-04=25 |
| cell_disposition_micros — Cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 158 | 1 | 132.41% | none |
| component_post_return_micros — Component canonical post-return | microseconds | 2401 | 7 | 0 | 0 | 41 | 0 | 204.92% | none |
| outcome_classification_micros — Outcome classification | microseconds | 2401 | 7 | 0 | 0 | 3 | 0 | 374.71% | none |
| post_invocation_cleanup_micros — Post-invocation cleanup | microseconds | 2401 | 7 | 16 | 30 | 1417 | 8 | 106.17% | none |
| reusable_proof_micros — Reusable-proof return | microseconds | 2401 | 7 | 0 | 0 | 2 | 0 | 429.88% | none |

### Process resources (per-run peak)

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| process_peak_file_descriptor_count — Process peak file-descriptor count | count | 7 | 7 | 5 | 5 | 5 | 0 | 0.00% | none |
| process_peak_listening_socket_count — Process peak listening sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_open_socket_count — Process peak open sockets | count | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| process_peak_rss_bytes — Process peak RSS | bytes | 7 | 7 | 18022400 | 18202624 | 18448384 | 139264 | 0.94% | none |
| process_peak_thread_count — Process peak thread count | count | 7 | 7 | 4 | 4 | 4 | 0 | 0.00% | none |
| process_peak_virtual_memory_bytes — Process peak virtual memory | bytes | 7 | 7 | 231800832 | 231804928 | 231931904 | 4096 | 0.02% | run-01=231931904 |

### Queueing and release

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | microseconds | 2401 | 7 | 0 | 5 | 5652 | 3 | 173.72% | run-04=5; run-05=5; run-07=5 |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | microseconds | 2401 | 7 | 1 | 3 | 158 | 1 | 132.41% | none |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | microseconds | 623 | 7 | 1196 | 2413 | 5652 | 514 | 36.28% | none |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | microseconds | 7 | 7 | 28 | 37 | 41 | 4 | 14.29% | none |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | microseconds | 7 | 7 | 0 | 0 | 0 | 0 | n/a | none |

### Startup and preparation

| Metric | Unit | Samples | Runs | Min | Median | Max | MAD | CV | Run-level outliers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| capsule_validation_and_load_micros — Capsule validation and component load | microseconds | 7 | 7 | 55 | 56 | 67 | 1 | 7.72% | run-01=67; run-04=63 |
| component_preparation_micros — Component preparation | microseconds | 7 | 7 | 49152 | 49609 | 49978 | 194 | 0.59% | none |
| prepared_component_release_micros — Prepared-component release | microseconds | 7 | 7 | 63 | 70 | 78 | 2 | 7.36% | none |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | microseconds | 7 | 7 | 148413 | 149519 | 366662 | 176 | 45.48% | run-01=366662; run-03=150488; run-06=148413 |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | microseconds | 7 | 7 | 3919 | 4064 | 57877 | 131 | 173.20% | run-01=57877 |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | microseconds | 7 | 7 | 159 | 168 | 187 | 8 | 6.35% | none |

## Environmental noise and outliers

Outliers use per-run representative values and a robust z-score above 3.5, or any deviation from a zero-MAD run-level median. Flags remain in the aggregate and raw archive; they prompt investigation or rerun and never permit discarding a run.

| Metric | Flagged runs |
|---|---|
| activation_acquire_or_queue_wait_micros | run-04=5 (deviates from a zero-MAD run-level median); run-05=5 (deviates from a zero-MAD run-level median); run-07=5 (deviates from a zero-MAD run-level median) |
| activation_resource_reclamation_micros | run-01=23 (deviates from a zero-MAD run-level median); run-02=26 (deviates from a zero-MAD run-level median); run-04=25 (deviates from a zero-MAD run-level median) |
| at_capacity_activations_per_second | run-07=549.58 (run-level robust z-score exceeds 3.5) |
| bounded_queue_saturation_activations_per_second | run-07=952.53 (run-level robust z-score exceeds 3.5) |
| capsule_validation_and_load_micros | run-01=67 (run-level robust z-score exceeds 3.5); run-04=63 (run-level robust z-score exceeds 3.5) |
| process_launch_to_completion_real_executable_micros | run-02=55865.50 (run-level robust z-score exceeds 3.5) |
| process_launch_to_ready_to_invoke_micros | run-01=366662 (run-level robust z-score exceeds 3.5); run-03=150488 (run-level robust z-score exceeds 3.5); run-06=148413 (run-level robust z-score exceeds 3.5) |
| process_launch_to_runtime_ready_micros | run-01=57877 (run-level robust z-score exceeds 3.5) |
| process_peak_virtual_memory_bytes | run-01=231931904 (run-level robust z-score exceeds 3.5) |
| recovery_after_cancellation_elapsed_micros | run-03=169.50 (run-level robust z-score exceeds 3.5) |
| recovery_after_domain_error_elapsed_micros | run-04=114.50 (run-level robust z-score exceeds 3.5) |
| warm_activation_elapsed_micros | run-06=170 (run-level robust z-score exceeds 3.5) |

## Phase 1 advisory comparison bands

The bands are like-for-like native-Linux regression-detection aids, not SLOs, release promises, or cross-machine claims. Candidates need at least seven comparable full-profile processes and all hard invariants must pass.

| Metric | Direction | Reference run median | Advisory noise band | Candidate regression rule |
|---|---|---:|---:|---|
| activation_acquire_or_queue_wait_micros — Activation acquire or queue wait | higher is worse | 4 | 10 | candidate median > reference median + advisory_noise_band |
| activation_cell_disposition_micros — Activation cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| activation_queued_acquire_wait_micros — Queued activation acquire wait | higher is worse | 2425.50 | 242.55 | candidate median > reference median + advisory_noise_band |
| activation_resource_reclamation_micros — Activation-resource reclamation | higher is worse | 27 | 10 | candidate median > reference median + advisory_noise_band |
| at_capacity_activations_per_second — At-capacity activation throughput | lower is worse | 626.53 | 93.98 | candidate median < reference median - advisory_noise_band |
| bounded_queue_saturation_activations_per_second — Bounded-queue-saturation activation throughput | lower is worse | 1053.22 | 157.98 | candidate median < reference median - advisory_noise_band |
| cancellation_overshoot_micros — Cancellation interruption overshoot | higher is worse | 2197.50 | 219.75 | candidate median > reference median + advisory_noise_band |
| capsule_validation_and_load_micros — Capsule validation and component load | higher is worse | 56 | 10 | candidate median > reference median + advisory_noise_band |
| cell_disposition_micros — Cell release or quarantine disposition | higher is worse | 3 | 10 | candidate median > reference median + advisory_noise_band |
| cold_activation_elapsed_micros — Cold activation inside real executable harness | higher is worse | 220 | 22 | candidate median > reference median + advisory_noise_band |
| component_post_return_micros — Component canonical post-return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| component_preparation_micros — Component preparation | higher is worse | 49609 | 4960.90 | candidate median > reference median + advisory_noise_band |
| fixed_pool_acquire_p50_micros — Fixed-pool acquire P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| fixed_pool_queued_wait_p50_micros — Fixed-pool queued wait P50 | higher is worse | 37 | 12 | candidate median > reference median + advisory_noise_band |
| fixed_pool_release_p50_micros — Fixed-pool release P50 | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| outcome_classification_micros — Outcome classification | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| post_invocation_cleanup_micros — Post-invocation cleanup | higher is worse | 30 | 10 | candidate median > reference median + advisory_noise_band |
| prepared_component_release_micros — Prepared-component release | higher is worse | 70 | 10 | candidate median > reference median + advisory_noise_band |
| process_launch_to_completion_real_executable_micros — Real executable process launch to completion | higher is worse | 52982.50 | 5298.25 | candidate median > reference median + advisory_noise_band |
| process_launch_to_ready_to_invoke_micros — Derived external process launch to ready-to-invoke | higher is worse | 149519 | 14951.90 | candidate median > reference median + advisory_noise_band |
| process_launch_to_runtime_ready_micros — External process launch to runtime/pool ready | higher is worse | 4064 | 406.40 | candidate median > reference median + advisory_noise_band |
| process_peak_rss_bytes — Process peak RSS | higher is worse | 18202624 | 1820262.40 | candidate median > reference median + advisory_noise_band |
| process_peak_virtual_memory_bytes — Process peak virtual memory | higher is worse | 231804928 | 23180492.80 | candidate median > reference median + advisory_noise_band |
| recovery_after_cancellation_elapsed_micros — Recovery after cancellation | higher is worse | 188 | 18.80 | candidate median > reference median + advisory_noise_band |
| recovery_after_domain_error_elapsed_micros — Recovery after domain error | higher is worse | 170 | 30 | candidate median > reference median + advisory_noise_band |
| recovery_after_memory_pressure_elapsed_micros — Recovery after memory pressure | higher is worse | 172.50 | 39 | candidate median > reference median + advisory_noise_band |
| recovery_after_timeout_elapsed_micros — Recovery after timeout | higher is worse | 192.50 | 19.25 | candidate median > reference median + advisory_noise_band |
| recovery_after_trap_elapsed_micros — Recovery after trap | higher is worse | 133 | 46.50 | candidate median > reference median + advisory_noise_band |
| reusable_proof_micros — Reusable-proof return | higher is worse | 0 | 10 | candidate median > reference median + advisory_noise_band |
| timeout_overshoot_micros — Timeout interruption overshoot | higher is worse | 643 | 201 | candidate median > reference median + advisory_noise_band |
| trap_elapsed_micros — Trap containment latency | higher is worse | 147.50 | 57 | candidate median > reference median + advisory_noise_band |
| warm_activation_elapsed_micros — Warm activation latency | higher is worse | 150 | 15 | candidate median > reference median + advisory_noise_band |
| wasmtime_engine_construction_micros — Wasmtime engine/backend construction | higher is worse | 168 | 24 | candidate median > reference median + advisory_noise_band |

An inside-band candidate with at least seven valid comparable runs, a stable environment, all hard invariants passing, and no material run-level outlier is terminally **no detectable regression** (or statistically indistinguishable). Insufficient samples, environment instability, material outliers, or a failed invariant invalidate the comparison and require a fresh rerun after the invalid condition is resolved. A deterioration outside a band is a regression candidate that requires a second comparable set; repeated outside-band deterioration confirms the regression.

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
