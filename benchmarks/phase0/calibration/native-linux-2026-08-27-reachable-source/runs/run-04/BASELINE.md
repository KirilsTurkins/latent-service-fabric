# Phase 0 activation and resource baseline

**Status:** PASS
**Schema:** `latent.phase0.baseline.v2`
**Generated:** Unix epoch 1787820406360 ms
**Raw results:** `/home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/runs/run-04/raw-results.json`

> Observational Phase 0 evidence only. These values are not production SLOs, scaling commitments, or competitive claims.

## Environment

| Field | Value |
|---|---|
| OS | linux |
| Architecture | x86_64 |
| Kernel | Linux 7.1.5-201.fc44.x86_64 #1 SMP PREEMPT_DYNAMIC Tue Jul 28 14:16:30 UTC 2026 x86_64 GNU/Linux |
| CPU | AMD Ryzen 3 3200G with Radeon Vega Graphics |
| Logical CPUs | 4 |
| Memory | 16699981824 bytes (15926.34 MiB) |
| Rust | rustc 1.97.1 (8bab26f4f 2026-07-14)<br>binary: rustc<br>commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452<br>commit-date: 2026-07-14<br>host: x86_64-unknown-linux-gnu<br>release: 1.97.1<br>LLVM version: 22.1.6 |
| Cargo | cargo 1.97.1 (c980f4866 2026-06-30) |
| Target | x86_64-unknown-linux-gnu |
| Build profile | release |
| Wasmtime | 47.0.3 (workspace pin) |
| Repository commit | 49e24fdbee1a3cde1a09fdb3bf8dcf640cc956c3 |

## Runtime configuration and pass/fail thresholds

| Field | Value |
|---|---:|
| Mode | Full |
| Independent issue-23 cold samples | 12 |
| Warm echo samples | 40 |
| Mixed-sequence repetitions | 10 |
| Throughput batches per mode | 24 |
| Pool iterations per worker | 2000 |
| Runtime workers | 2 |
| Pool capacity | 2 |
| Pool queue capacity | 4 |
| Fuel grant | 1000000000000 |
| Memory grant | 16777216 bytes (16.00 MiB) |
| Memory-pressure grant | 4194304 bytes (4.00 MiB) |
| Timeout | 25 ms |
| Cancellation delay | 5 ms |
| Maximum interruption overshoot | 500 ms |
| RSS growth allowance | 67108864 bytes (64.00 MiB) |
| File-descriptor growth allowance | 2 |

## Exact issue-23 executable probe

Cold samples come from fresh launches of the real `latentd phase0-spike invoke-once` command. The same checked executable probe also retains trap, timeout, and same-composition post-trap recovery documents; all use the shared Phase 0 composition API.

| Metric | N | Min | P50 | P95 | P99 | Max | Mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| Process launch to completion | 12 | 50779 | 51749 | 53508 | 53508 | 53508 | 52012.4 |
| Cold activation inside issue-23 harness | 12 | 200 | 212 | 219 | 219 | 219 | 211.2 |
Exact failure/recovery probes retained: 3.

## Startup and preparation

| Metric | Microseconds |
|---|---:|
| External process launch to runtime/pool ready | 3681 |
| Rust entry to observed worker/pool readiness | 2503 |
| Capsule validation and component load | 61 |
| Wasmtime engine/backend construction | 157 |
| Component preparation | 48315 |
| Rust entry to retained invocation readiness | 53177 |
| Prepared-component release | 89 |

## Activation and cleanup distributions

Percentiles use nearest-rank ordering over the raw samples. The typed guest-call interval includes Wasmtime's automatic canonical post-return; backend boundaries then separately record setup, in-guest host imports, host-visible post-call result accounting, activation-resource reclamation, outcome classification, reusable-proof return, and cell disposition. `post_invocation_cleanup_micros` is the authoritative sum after the host-visible guest-call completion boundary; `backend_resource_cleanup_micros` is retained only as a residual interval.

| Metric | N | Min | P50 | P95 | P99 | Max | Mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| acquire_or_queue_wait_micros | 343 | 1 | 5 | 2441 | 2849 | 3614 | 537.9 |
| activation_resource_reclamation_micros | 343 | 17 | 25 | 56 | 173 | 271 | 32.7 |
| backend_resource_cleanup_micros | 343 | 23 | 37 | 72 | 191 | 280 | 44.1 |
| backend_setup_micros | 343 | 33 | 67 | 125 | 144 | 1214 | 74.5 |
| backend_total_micros | 343 | 87 | 1165 | 7152 | 25730 | 25967 | 1784.4 |
| cancellation_elapsed_micros | 10 | 7173 | 7382 | 8294 | 8294 | 8294 | 7523.6 |
| cancellation_overshoot_micros | 10 | 2173 | 2382 | 3294 | 3294 | 3294 | 2523.6 |
| cell_disposition_micros | 343 | 1 | 3 | 7 | 9 | 27 | 3.5 |
| cold_echo_elapsed_micros | 12 | 200 | 212 | 219 | 219 | 219 | 211.2 |
| component_post_return_micros | 343 | 0 | 0 | 2 | 3 | 6 | 0.5 |
| contained_execution_micros | 343 | 63 | 1133 | 7099 | 25678 | 25918 | 1740.3 |
| domain_error_elapsed_micros | 10 | 107 | 168 | 272 | 272 | 272 | 170.3 |
| guest_call_micros | 343 | 26 | 1084 | 7020 | 25638 | 25878 | 1670.6 |
| host_call_micros | 343 | 0 | 1 | 1 | 2 | 3 | 0.7 |
| memory_pressure_elapsed_micros | 10 | 2215 | 2306 | 2503 | 2503 | 2503 | 2347.5 |
| outcome_classification_micros | 343 | 0 | 0 | 1 | 1 | 2 | 0.1 |
| post_invocation_cleanup_micros | 343 | 19 | 29 | 66 | 181 | 278 | 36.8 |
| process_launch_to_completion_real_executable_micros | 12 | 50779 | 51749 | 53508 | 53508 | 53508 | 52012.4 |
| recovery_after_cancellation_elapsed_micros | 10 | 142 | 164 | 239 | 239 | 239 | 189.3 |
| recovery_after_domain_error_elapsed_micros | 10 | 102 | 114 | 207 | 207 | 207 | 140.4 |
| recovery_after_memory_pressure_elapsed_micros | 10 | 151 | 187 | 249 | 249 | 249 | 186.4 |
| recovery_after_timeout_elapsed_micros | 10 | 145 | 190 | 270 | 270 | 270 | 193.8 |
| recovery_after_trap_elapsed_micros | 10 | 103 | 135 | 264 | 264 | 264 | 149.4 |
| retained_first_echo_elapsed_micros | 1 | 296 | 296 | 296 | 296 | 296 | 296.0 |
| reusable_proof_micros | 343 | 0 | 0 | 0 | 1 | 3 | 0.0 |
| throughput_at_capacity_elapsed_micros | 48 | 1155 | 1256 | 1857 | 2484 | 2484 | 1409.5 |
| throughput_bounded_queue_saturation_elapsed_micros | 144 | 1188 | 2432 | 3785 | 4705 | 4968 | 2522.9 |
| timeout_elapsed_micros | 10 | 25223 | 25615 | 25993 | 25993 | 25993 | 25647.3 |
| timeout_overshoot_micros | 10 | 223 | 615 | 993 | 993 | 993 | 647.3 |
| total_invocation_micros | 343 | 102 | 1260 | 7185 | 25770 | 25993 | 2350.8 |
| trap_elapsed_micros | 10 | 111 | 123 | 200 | 200 | 200 | 147.3 |
| warm_echo_elapsed_micros | 40 | 103 | 147 | 244 | 249 | 249 | 158.3 |

## Fixed-pool and activation throughput

| Metric | At capacity | Bounded queue saturation |
|---|---:|---:|
| Activations | 48 | 144 |
| Activations/second | 648.9 | 1091.5 |
| Maximum active leases | 2 | 2 |
| Maximum queue depth | 0 | 4 |
| Acquire-wait P95 (us) | 9 | 2573 |
| Queued acquire-wait P95 (us) | n/a | 2787 |

## Invariant checks

| Check | Result | Expected | Observed |
|---|---|---|---|
| real_issue23_executable_probe_passed | PASS | at least three successful fresh-process calls through latentd phase0-spike with clean shutdown and unchanged topology | 12 fresh process samples |
| real_issue23_executable_failure_and_recovery_probe_passed | PASS | exact issue-23 executable probes cover trap, timeout, and same-composition post-trap recovery | 3 failure/recovery executable samples |
| linux_process_resource_probe_supported | PASS | Linux /proc resource probe available | supported |
| configured_runtime_workers_observed_before_and_after_loading | PASS | 2 | before=2, after=2 |
| prepared_cache_bounded_after_prepare | PASS | one retained entry within configured entry and byte limits | entries=1, source_bytes=27616, maximum_entries=1, maximum_source_bytes=67108864 |
| fixed_pool_queue_saturation_is_bounded | PASS | active=2, queued=4, then one additional waiter rejected | active=2, queued=4, overflow_rejected=true, error_code=resource_exhausted |
| fixed_pool_returns_to_configured_idle_state | PASS | capacity=2, available=2, active=0, queued=0, quarantined=0 | PoolSnapshotReport { capacity: 2, available: 2, queue_depth: 0, active_leases: 0, quarantined: 0 } |
| real_activation_throughput_reaches_pool_capacity | PASS | active=2 and queued=0 during complete runner/backend activations | active=2, queued=0 |
| real_activation_throughput_reaches_bounded_queue_saturation | PASS | active=2 and queued=4 during complete runner/backend activations | active=2, queued=4, queued_distribution=true |
| activation_owned_state_returns_to_baseline_after_every_sample | PASS | no active lease, waiter, cancellation registration, invocation, store, host state, instance, temporary buffer, cancellation probe, retained log, quarantine, or cache growth | 343 samples clean |
| all_scenarios_return_expected_terminal_outcomes | PASS | success/domain_error/trap/timeout/cancelled/resource_exhausted as requested | cancelled=10, domain_error=10, resource_exhausted=10, success=293, timeout=10, trap=10 |
| failure_does_not_degrade_the_next_cause_specific_echo | PASS | every failure is immediately followed by a distinctly labelled successful recovery echo | all cause-specific recovery echoes succeeded |
| timeout_and_cancellation_overshoot_are_bounded | PASS | each overshoot <= 500000 microseconds | timeout_max=993us, cancellation_max=3294us |
| topology_constant_across_component_loading_and_repeated_invocations | PASS | process/socket/listener/cell topology constant, runtime workers=2, and one bounded Wasmtime epoch thread after preparation | workers=2..2, processes=1..1, completed-snapshot active_max=0, queue_max=0, processes=1..1, threads=3..4, open_sockets=0..0, listeners=0..0 |
| rss_has_no_unbounded_monotonic_growth | PASS | steady-state range and net growth <= 67108864 bytes | samples=343, min=17719296, max=17969152, range=249856, first=17719296, last=17969152, net_growth=249856, monotonic_non_decreasing=true, allowance=67108864 |
| file_descriptors_have_no_unbounded_monotonic_growth | PASS | steady-state range and net growth <= 2 descriptors | samples=343, min=5, max=5, range=0, first=5, last=5, net_growth=0, monotonic_non_decreasing=true, allowance=2 |
| explicit_release_clears_prepared_cache | PASS | entries=0 and source_bytes=0 | entries=0, source_bytes=0 |
| post_release_backend_and_pool_are_clean | PASS | all live backend resources zero and fixed pool fully available | backend=RuntimeResourceReport { active_invocations: 0, live_stores: 0, live_host_states: 0, live_component_instances: 0, live_temporary_buffers: 0, live_cancellation_probes: 0, stores_created: 343 }, pool=PoolSnapshotReport { capacity: 2, available: 2, queue_depth: 0, active_leases: 0, quarantined: 0 } |
| runtime_shutdown_returns_thread_count_to_process_baseline | PASS | observed Tokio workers=0 and at most 2 OS threads | observed_workers=0, os_threads=1 |

## Conclusions

- The exact issue-23 executable path passed every independent cold-start correctness, topology, and clean-shutdown probe.
- All configured fixed-capacity, queue-saturation, cleanup, and bounded-growth invariants passed for this sample window.
- Trap, timeout, cancellation, domain error, and memory-pressure samples did not prevent the immediately following cause-specific recovery echo from succeeding.

## Limitations and comparison rules

- Measurements are observations from finite local processes and are not production SLOs, capacity guarantees, or competitive claims.
- The mandatory executable probe launches the exact issue-23 `latentd phase0-spike` commands for independent cold success, trap, timeout, and post-trap recovery samples. Retained measurements construct their runtime, preparation, bounded cache/log configuration, bindings, and activation runner through that same shared composition API.
- Post-invocation cleanup is timed inside `Phase0WasmtimeBackend` from the host-visible typed guest-call completion boundary (after Wasmtime's automatic canonical post-return) through post-call result accounting, activation-resource reclamation, outcome classification, and reusable-proof return, then adds cell disposition. The legacy backend residual remains for comparison only and is not presented as isolated cleanup.
- Each coordinated throughput probe briefly holds real leases after acquisition until the raw pool observes its required state: pool capacity with no queued waiter, or pool and bounded-queue capacity together. No synthetic lease or backend result is used. Raw acquisition timing excludes that coordination pause, while batch latency includes it as a stress-observation cost.
- Wall-clock distributions include host scheduling noise; compare only like-for-like hardware, kernel, toolchain, target, profile, fixture digest, and runtime configuration.
- RSS allocators and Wasmtime may retain bounded arenas after first use; the invariant checks bounded range and monotonic growth after warm-up rather than requiring byte-for-byte return.
- Linux /proc supplies RSS, virtual memory, thread, descriptor, and socket probes. Unsupported platforms fail the strict reference run instead of silently omitting evidence.
- Compare runs only when CPU, memory, OS/kernel, Rust, Wasmtime, target, build profile, pool topology, limits, fixture digest, and sample configuration are recorded and materially equivalent.
