fn run(cli: Cli, process_entry: Instant) -> Result<bool, BenchError> {
    let config = EffectiveConfig::from_cli(&cli)?;
    if let Some(workload) = config.profile_workload {
        return run_targeted_profile(cli, config, workload, process_entry);
    }
    let initial_snapshot = observe_process("process_entry", process_entry);

    let shared_runtime = phase0_composition::construct_runtime_composition(&Phase0RuntimeConfig {
        node_id: NodeId(NODE_ID.to_owned()),
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        runtime_workers: config.runtime_workers,
    })
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0RuntimeComposition {
        runtime,
        pool,
        workers,
    } = shared_runtime;
    runtime
        .block_on(phase0_composition::wait_for_runtime_workers(
            &workers,
            config.runtime_workers,
        ))
        .map_err(platform_error)?;
    let rust_entry_to_runtime_ready_micros = elapsed_micros(process_entry);
    let process_launch_to_runtime_ready_micros = now_unix_micros()
        .saturating_sub(cli.parent_launch_unix_micros);
    let runtime_ready_snapshot = observe_process("before_component_load", process_entry);
    let before_component_load = TopologySnapshot {
        label: "before_component_load".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: runtime_ready_snapshot.clone(),
        pool: pool_snapshot(&pool.observations()),
    };

    let mut result = runtime.block_on(run_async(
        &cli,
        &config,
        Arc::clone(&pool),
        workers.clone(),
        before_component_load,
        process_entry,
    ))?;
    result
        .process_snapshots
        .insert(0, runtime_ready_snapshot.clone());
    result.process_snapshots.insert(0, initial_snapshot.clone());

    drop(pool);
    drop(runtime);
    std::thread::sleep(Duration::from_millis(25));
    let final_snapshot = observe_process("runtime_stopped", process_entry);
    let final_thread_pass = match (initial_snapshot.thread_count, final_snapshot.thread_count) {
        (Some(initial), Some(final_count)) => final_count <= initial.saturating_add(1),
        _ => false,
    };
    result.checks.push(Check {
        name: "runtime_shutdown_returns_thread_count_to_process_baseline".to_owned(),
        passed: final_thread_pass && workers.active_workers() == 0,
        expected: format!(
            "observed Tokio workers=0 and at most {} OS threads",
            initial_snapshot.thread_count.unwrap_or(0).saturating_add(1)
        ),
        observed: format!(
            "observed_workers={}, os_threads={}",
            workers.active_workers(),
            final_snapshot
                .thread_count
                .map_or_else(|| "unsupported".to_owned(), |value| value.to_string())
        ),
    });
    result.process_snapshots.push(final_snapshot);

    let environment = environment_report();
    let all_passed = result.checks.iter().all(|check| check.passed);
    let status = if all_passed { "pass" } else { "fail" }.to_owned();
    let limitations = vec![
        "Measurements are observations from finite local processes and are not production SLOs, capacity guarantees, or competitive claims.".to_owned(),
        "The mandatory executable probe launches the exact issue-23 `latentd phase0-spike` commands for independent cold success, trap, timeout, and post-trap recovery samples. Retained measurements construct their runtime, preparation, bounded cache/log configuration, bindings, and activation runner through that same shared composition API.".to_owned(),
        "Post-invocation cleanup is timed inside `Phase0WasmtimeBackend` from the host-visible typed guest-call completion boundary (after Wasmtime's automatic canonical post-return) through post-call result accounting, activation-resource reclamation, outcome classification, and reusable-proof return, then adds cell disposition. The legacy backend residual remains for comparison only and is not presented as isolated cleanup.".to_owned(),
        "Each coordinated throughput probe briefly holds real leases after acquisition until the raw pool observes its required state: pool capacity with no queued waiter, or pool and bounded-queue capacity together. No synthetic lease or backend result is used. Raw acquisition timing excludes that coordination pause, while batch latency includes it as a stress-observation cost.".to_owned(),
        "Wall-clock distributions include host scheduling noise; compare only like-for-like hardware, kernel, toolchain, target, profile, fixture digest, and runtime configuration.".to_owned(),
        "RSS allocators and Wasmtime may retain bounded arenas after first use; the invariant checks bounded range and monotonic growth after warm-up rather than requiring byte-for-byte return.".to_owned(),
        "Linux /proc supplies RSS, virtual memory, thread, descriptor, and socket probes. Unsupported platforms fail the strict reference run instead of silently omitting evidence.".to_owned(),
    ];
    let conclusions = if all_passed {
        vec![
            "The exact issue-23 executable path passed every independent cold-start correctness, topology, and clean-shutdown probe.".to_owned(),
            "All configured fixed-capacity, queue-saturation, cleanup, and bounded-growth invariants passed for this sample window.".to_owned(),
            "Trap, timeout, cancellation, domain error, and memory-pressure samples did not prevent the immediately following cause-specific recovery echo from succeeding.".to_owned(),
        ]
    } else {
        vec![
            "At least one configured invariant failed; inspect the raw checks and samples before using this run as reference evidence.".to_owned(),
        ]
    };

    let document = BaselineDocument {
        schema_version: SCHEMA_VERSION,
        generated_at_unix_millis: now_unix_millis(),
        status,
        observational_only: true,
        production_ready: false,
        phase1_api_compatible: false,
        environment,
        artifact: result.artifact,
        config: config.clone(),
        executable_harness: result.executable_harness,
        preparation_cache_reuse: result.preparation_cache_reuse,
        timings: TimingReport {
            process_launch_to_runtime_ready_micros,
            rust_entry_to_runtime_ready_micros,
            capsule_validation_and_load_micros: result.validation_micros,
            wasmtime_engine_construction_micros: result.engine_micros,
            component_preparation_micros: result.preparation_micros,
            rust_entry_to_first_invocation_ready_micros: result.first_invocation_ready_micros,
            prepared_component_release_micros: result.prepared_release_micros,
            distributions: result.distributions,
        },
        pool_probe: result.pool_probe,
        activation_throughput: result.activation_throughput,
        activation_samples: result.activation_samples,
        process_snapshots: result.process_snapshots,
        topology_snapshots: result.topology_snapshots,
        checks: result.checks,
        limitations,
        conclusions,
    };

    write_outputs(&cli.output_json, &cli.output_report, &document)?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema_version": SCHEMA_VERSION,
            "status": document.status,
            "raw_results": cli.output_json,
            "report": cli.output_report,
        }))?
    );
    Ok(all_passed)
}

/// Runs one profiler boundary without performing the unrelated full-baseline
/// phases.  The wrapper that invokes this mode retains a separate full run for
/// the same source/configuration, so targeted sampling cannot weaken a hard
/// invariant claim.
fn run_targeted_profile(
    cli: Cli,
    config: EffectiveConfig,
    workload: ProfileWorkload,
    process_entry: Instant,
) -> Result<bool, BenchError> {
    let initial_snapshot = observe_process("process_entry", process_entry);
    let shared_runtime = phase0_composition::construct_runtime_composition(&Phase0RuntimeConfig {
        node_id: NodeId(NODE_ID.to_owned()),
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        runtime_workers: config.runtime_workers,
    })
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0RuntimeComposition {
        runtime,
        pool,
        workers,
    } = shared_runtime;
    runtime
        .block_on(phase0_composition::wait_for_runtime_workers(
            &workers,
            config.runtime_workers,
        ))
        .map_err(platform_error)?;
    let rust_entry_to_runtime_ready_micros = elapsed_micros(process_entry);
    let process_launch_to_runtime_ready_micros = now_unix_micros()
        .saturating_sub(cli.parent_launch_unix_micros);
    let runtime_ready_snapshot = observe_process("before_component_load", process_entry);
    let before_component_load = TopologySnapshot {
        label: "before_component_load".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: runtime_ready_snapshot.clone(),
        pool: pool_snapshot(&pool.observations()),
    };

    let mut result = runtime.block_on(run_targeted_async(
        &cli,
        &config,
        workload,
        Arc::clone(&pool),
        workers.clone(),
        before_component_load,
        process_entry,
    ))?;
    result.process_snapshots.insert(0, runtime_ready_snapshot.clone());
    result.process_snapshots.insert(0, initial_snapshot.clone());

    drop(pool);
    drop(runtime);
    std::thread::sleep(Duration::from_millis(25));
    let final_snapshot = observe_process("runtime_stopped", process_entry);
    let final_thread_pass = match (initial_snapshot.thread_count, final_snapshot.thread_count) {
        (Some(initial), Some(final_count)) => final_count <= initial.saturating_add(1),
        _ => false,
    };
    result.checks.push(Check {
        name: "targeted_profile_runtime_shutdown_returns_to_process_baseline".to_owned(),
        passed: final_thread_pass && workers.active_workers() == 0,
        expected: format!(
            "observed Tokio workers=0 and at most {} OS threads",
            initial_snapshot.thread_count.unwrap_or(0).saturating_add(1)
        ),
        observed: format!(
            "observed_workers={}, os_threads={}",
            workers.active_workers(),
            final_snapshot
                .thread_count
                .map_or_else(|| "unsupported".to_owned(), |value| value.to_string())
        ),
    });
    result.process_snapshots.push(final_snapshot);

    let all_passed = result.checks.iter().all(|check| check.passed);
    let status = if all_passed { "pass" } else { "fail" }.to_owned();
    let document = TargetedProfileDocument {
        schema_version: TARGETED_PROFILE_SCHEMA,
        generated_at_unix_millis: now_unix_millis(),
        status,
        observational_only: true,
        profile_workload: workload,
        workload_semantics: workload.semantics().to_owned(),
        full_invariant_proof_required: true,
        environment: environment_report(),
        artifact: result.artifact,
        config: config.clone(),
        preparation_cache_reuse: result.preparation_cache_reuse,
        timings: TimingReport {
            process_launch_to_runtime_ready_micros,
            rust_entry_to_runtime_ready_micros,
            capsule_validation_and_load_micros: result.validation_micros,
            wasmtime_engine_construction_micros: result.engine_micros,
            component_preparation_micros: result.preparation_micros,
            rust_entry_to_first_invocation_ready_micros: result.first_invocation_ready_micros,
            prepared_component_release_micros: result.prepared_release_micros,
            distributions: result.distributions,
        },
        activation_throughput: result.activation_throughput,
        targeted_contention: result.targeted_contention,
        activation_samples: result.activation_samples,
        process_snapshots: result.process_snapshots,
        topology_snapshots: result.topology_snapshots,
        selected_scenarios: result.selected_scenarios,
        payload_flow: result.payload_flow,
        checks: result.checks,
        limitations: vec![
            "This is a scenario-selective profiler document. Its adjacent full baseline proof, not this reduced check set, establishes the complete Phase 0 invariant set.".to_owned(),
            "Payload-flow byte counters record bytes passed into and returned from the typed call. They do not claim every byte was copied; copy attribution requires narrow profiler symbols.".to_owned(),
            "A nonzero coordination polling interval is profiler-only methodology and is not comparable to the calibrated throughput interval.".to_owned(),
        ],
    };
    write_targeted_profile_outputs(&cli.output_json, &cli.output_report, &document)?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema_version": TARGETED_PROFILE_SCHEMA,
            "status": document.status,
            "profile_workload": workload.name(),
            "raw_results": cli.output_json,
            "report": cli.output_report,
        }))?
    );
    Ok(all_passed)
}

fn targeted_runner(
    runner: Option<&Arc<Phase0ActivationRunner>>,
    workload: ProfileWorkload,
) -> Result<&Arc<Phase0ActivationRunner>, BenchError> {
    runner.ok_or_else(|| {
        BenchError::new(format!(
            "targeted workload {} unexpectedly has no activation runner",
            workload.name()
        ))
    })
}

/// Measures a single same-key cache observation without conflating it with an
/// activation.  Cache-disabled runs intentionally do not call `prepare`
/// twice: the backend correctly rejects concurrent runner-scoped preparation,
/// so their valid control is an explicit no-reuse state rather than a fake hit.
async fn observe_prepared_cache_reuse(
    backend: &Arc<Phase0WasmtimeBackend>,
    artifact: &CapsuleArtifact,
    preparation_key: &PreparationKey,
    first_prepared: &PreparedComponent,
    first_prepare_micros: u64,
    cache_enabled: bool,
) -> Result<PreparedCacheReuseReport, BenchError> {
    if !cache_enabled {
        let snapshot = backend.cache_snapshot();
        return Ok(PreparedCacheReuseReport {
            cache_enabled: false,
            first_prepare_micros,
            second_prepare_micros: None,
            same_prepared_handle: None,
            cache_entries_after_probe: snapshot.entries,
            status: "disabled_cold_control".to_owned(),
        });
    }

    let second_started = Instant::now();
    let second_prepared = backend
        .prepare(artifact, preparation_key)
        .await
        .map_err(platform_error)?;
    let second_prepare_micros = duration_micros(second_started.elapsed());
    let snapshot = backend.cache_snapshot();
    let same_prepared_handle = first_prepared.opaque_handle == second_prepared.opaque_handle;
    let status = if same_prepared_handle && snapshot.entries == 1 {
        "cache_hit"
    } else {
        "cache_probe_failed"
    };
    Ok(PreparedCacheReuseReport {
        cache_enabled: true,
        first_prepare_micros,
        second_prepare_micros: Some(second_prepare_micros),
        same_prepared_handle: Some(same_prepared_handle),
        cache_entries_after_probe: snapshot.entries,
        status: status.to_owned(),
    })
}

#[allow(clippy::too_many_arguments)]
async fn run_targeted_async(
    cli: &Cli,
    config: &EffectiveConfig,
    workload: ProfileWorkload,
    pool: Arc<FixedCellPool>,
    workers: RuntimeWorkerMonitor,
    before_component_load: TopologySnapshot,
    process_entry: Instant,
) -> Result<TargetedAsyncRunResult, BenchError> {
    let collector = latentd::phase0_collector::native_collector_identity("phase0-baseline")
        .map_err(BenchError::new)?;
    let (capsule_path, capsule_digest, capsule_bytes) = capsule_identity(&cli.capsule)?;
    let prepared_backend = phase0_composition::prepare_phase0_backend(
        &Phase0PreparationConfig {
            capsule: cli.capsule.clone(),
            component: None,
            component_maximum_bytes: COMPONENT_MAXIMUM_BYTES,
            prepared_cache_maximum_entries: PREPARED_CACHE_MAXIMUM_ENTRIES,
            prepared_cache_maximum_bytes: PREPARED_CACHE_MAXIMUM_BYTES,
            prepared_cache_enabled: config.prepared_cache_enabled,
            invocation_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            invocation_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            retained_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            retained_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            requested_memory_bytes: config.memory_bytes.max(config.memory_pressure_bytes),
            requested_fuel: config.fuel,
            wasmtime_instance_allocator: config.wasmtime_allocator.into(),
            wasmtime_copy_on_write_images: config.wasmtime_copy_on_write_images,
            wasmtime_pooling_maximum_instances: config.pool_capacity,
        },
    )
    .await
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0PreparedBackend {
        loaded,
        backend,
        preparation_key,
        prepared,
        cache_after_prepare,
        timings: preparation_timings,
    } = prepared_backend;
    let timings = PhaseTimingRecorder::default();
    let throughput_saturation_gate = ThroughputSaturationGate::new();
    let pool_for_runner: Arc<dyn CellPool> = Arc::new(TimingCellPool::new(
        Arc::clone(&pool),
        timings.clone(),
        throughput_saturation_gate.clone(),
    ));
    let backend_for_runner: Arc<dyn ExecutionBackend> = Arc::new(TimingExecutionBackend::new(
        Arc::clone(&backend),
        timings.clone(),
    ));
    // Preparation-only and same-key cache-reuse profiles deliberately stop
    // before runner construction.  That makes their profiler boundary
    // different from first activation rather than merely changing an output
    // directory around a full process.
    let runner = if matches!(
        workload,
        ProfileWorkload::ColdPreparation | ProfileWorkload::PreparedCacheReuse
    ) {
        None
    } else {
        Some(
            phase0_composition::create_phase0_activation_runner(
                pool_for_runner,
                backend_for_runner,
                prepared.clone(),
            )
            .map_err(platform_error)?,
        )
    };
    let first_invocation_ready_micros = elapsed_micros(process_entry);
    let prepared_process = observe_process("after_component_preparation", process_entry);
    let after_component_preparation = TopologySnapshot {
        label: "after_component_preparation".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: prepared_process.clone(),
        pool: pool_snapshot(&pool.observations()),
    };

    let mut samples = Vec::new();
    let activation_throughput = None;
    let mut targeted_contention = None;
    let preparation_cache_reuse = if workload == ProfileWorkload::PreparedCacheReuse {
        Some(
            observe_prepared_cache_reuse(
                &backend,
                &loaded.artifact,
                &preparation_key,
                &prepared,
                preparation_timings.component_preparation_micros,
                config.prepared_cache_enabled,
            )
            .await?,
        )
    } else {
        None
    };
    match workload {
        ProfileWorkload::ColdPreparation | ProfileWorkload::PreparedCacheReuse => {}
        ProfileWorkload::FirstActivation => {
            let runner = targeted_runner(runner.as_ref(), workload)?;
            samples.push(
                invoke_case(
                    &loaded.artifact.manifest,
                    &pool,
                    &backend,
                    runner,
                    &timings,
                    &workers,
                    process_entry,
                    InvocationRequest {
                        scenario: "retained_first_echo",
                        iteration: 0,
                        input: "phase0 targeted first echo",
                        expected: ExpectedOutcome::Success,
                        memory_bytes: config.memory_bytes,
                        fuel: config.fuel,
                        timeout_ms: 1_000,
                        cancel_after_ms: None,
                    },
                )
                .await?,
            );
        }
        ProfileWorkload::WarmExecution => {
            let runner = targeted_runner(runner.as_ref(), workload)?;
            for iteration in 0..config.warm_samples {
                samples.push(
                    invoke_case(
                        &loaded.artifact.manifest,
                        &pool,
                        &backend,
                        runner,
                        &timings,
                        &workers,
                        process_entry,
                        InvocationRequest {
                            scenario: "warm_echo",
                            iteration,
                            input: "phase0 targeted warm echo",
                            expected: ExpectedOutcome::Success,
                            memory_bytes: config.memory_bytes,
                            fuel: config.fuel,
                            timeout_ms: 1_000,
                            cancel_after_ms: None,
                        },
                    )
                    .await?,
                );
            }
        }
        ProfileWorkload::FailureContainment => {
            let runner = targeted_runner(runner.as_ref(), workload)?;
            for iteration in 0..config.sequence_repetitions {
                append_mixed_sequence(
                    config,
                    &loaded.artifact.manifest,
                    &pool,
                    &backend,
                    runner,
                    &timings,
                    &workers,
                    process_entry,
                    iteration,
                    &mut samples,
                )
                .await?;
            }
        }
        ProfileWorkload::Cleanup => {
            let runner = targeted_runner(runner.as_ref(), workload)?;
            for iteration in 0..config.warm_samples {
                samples.push(
                    invoke_case(
                        &loaded.artifact.manifest,
                        &pool,
                        &backend,
                        runner,
                        &timings,
                        &workers,
                        process_entry,
                        InvocationRequest {
                            scenario: "cleanup_echo",
                            iteration,
                            input: "phase0 targeted cleanup echo",
                            expected: ExpectedOutcome::Success,
                            memory_bytes: config.memory_bytes,
                            fuel: config.fuel,
                            timeout_ms: 1_000,
                            cancel_after_ms: None,
                        },
                    )
                    .await?,
                );
            }
        }
        ProfileWorkload::AtCapacityContention | ProfileWorkload::QueuedContention => {
            let runner = targeted_runner(runner.as_ref(), workload)?;
            let mode = workload
                .contention_mode()
                .ok_or_else(|| BenchError::new("contention workload has no throughput mode"))?;
            targeted_contention = Some(TargetedContentionReport {
                mode: run_throughput_mode(
                    config,
                    &loaded.artifact.manifest,
                    &pool,
                    &backend,
                    runner,
                    &timings,
                    &throughput_saturation_gate,
                    &workers,
                    process_entry,
                    mode,
                    &mut samples,
                )
                .await?,
            });
        }
    }

    let mut selected_scenarios = samples
        .iter()
        .map(|sample| sample.scenario.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    if preparation_cache_reuse.is_some() {
        selected_scenarios = vec!["prepared_cache_reuse".to_owned()];
    }
    let expected_outcomes_pass = samples.iter().all(|sample| {
        sample.outcome.name == sample.expected_outcome && sample.contract_result_valid
    });
    let expected_cache = |snapshot: &CacheSnapshotReport| {
        if config.prepared_cache_enabled {
            snapshot.entries == 1 && snapshot.source_bytes == cache_after_prepare.source_bytes
        } else {
            snapshot.entries == 0 && snapshot.source_bytes == 0
        }
    };
    let per_activation_clean = samples.iter().all(|sample| {
        pool_is_clean(&sample.pool_after, config.pool_capacity)
            && sample.runner_after.active_cancellation_registrations == 0
            && sample.runner_after.running_invocations == 0
            && sample.runner_after.quarantined_cells == 0
            && sample.runner_after.disposition_failures == 0
            && resources_are_reclaimed(&sample.backend_resources_after)
            && sample.retained_log_entries_after_clear == 0
            && expected_cache(&sample.prepared_cache_after)
    });
    let failure_recovery_pass = match workload {
        ProfileWorkload::FailureContainment => cause_specific_failure_recovery_is_healthy(&samples),
        _ => true,
    };
    let contention_pass = targeted_contention.as_ref().is_none_or(|contention| match workload {
        ProfileWorkload::AtCapacityContention => {
            contention.mode.mode == ThroughputMode::AtCapacity.name()
                && contention.mode.maximum_observed_active_leases == config.pool_capacity
                && contention.mode.maximum_observed_queue_depth == 0
        }
        ProfileWorkload::QueuedContention => {
            contention.mode.mode == ThroughputMode::BoundedQueueSaturation.name()
                && contention.mode.maximum_observed_active_leases == config.pool_capacity
                && contention.mode.maximum_observed_queue_depth == config.pool_queue_capacity
                && contention.mode.queued_acquire_wait_micros.is_some()
        }
        _ => true,
    });
    let cache_reuse_pass = preparation_cache_reuse.as_ref().is_none_or(|probe| {
        if probe.cache_enabled {
            probe.status == "cache_hit"
                && probe.second_prepare_micros.is_some()
                && probe.same_prepared_handle == Some(true)
                && probe.cache_entries_after_probe == 1
        } else {
            probe.status == "disabled_cold_control"
                && probe.second_prepare_micros.is_none()
                && probe.same_prepared_handle.is_none()
                && probe.cache_entries_after_probe == 0
        }
    });

    let release_started = Instant::now();
    backend.release(prepared).await.map_err(platform_error)?;
    let prepared_release_micros = duration_micros(release_started.elapsed());
    backend.log_sink().clear();
    let cache_after_release = backend.cache_snapshot();
    let resources_after_release = backend.resource_snapshot();
    let pool_after_release = pool_snapshot(&pool.observations());
    let post_release = observe_process("prepared_component_released", process_entry);
    let mut topology_snapshots = vec![before_component_load, after_component_preparation];
    topology_snapshots.extend(samples.iter().map(|sample| TopologySnapshot {
        label: sample.process_after.label.clone(),
        observed_runtime_workers: sample.observed_runtime_workers_after,
        process: sample.process_after.clone(),
        pool: sample.pool_after.clone(),
    }));
    topology_snapshots.push(TopologySnapshot {
        label: "prepared_component_released".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: post_release.clone(),
        pool: pool_after_release.clone(),
    });
    let topology_pass = topology_is_constant(
        &topology_snapshots[0],
        &topology_snapshots[1],
        &topology_snapshots[2..],
        config,
    );
    let mut checks = vec![
        Check {
            name: "targeted_profile_selected_semantics".to_owned(),
            passed: true,
            expected: workload.semantics().to_owned(),
            observed: format!("workload={}, scenarios={selected_scenarios:?}", workload.name()),
        },
        Check {
            name: "targeted_profile_selected_outcomes_pass".to_owned(),
            passed: expected_outcomes_pass,
            expected: "every selected activation returns its requested outcome".to_owned(),
            observed: outcome_summary(&samples),
        },
        Check {
            name: "targeted_profile_reclaims_selected_activation_state".to_owned(),
            passed: per_activation_clean,
            expected: "selected activation state, logs, resources, and pool lease return to baseline".to_owned(),
            observed: format!("{} selected samples", samples.len()),
        },
        Check {
            name: "targeted_profile_failure_recovery_pass".to_owned(),
            passed: failure_recovery_pass,
            expected: "failure profile has immediate healthy cause-specific recovery".to_owned(),
            observed: if failure_recovery_pass { "passed".to_owned() } else { "failed".to_owned() },
        },
        Check {
            name: "targeted_profile_contention_state_pass".to_owned(),
            passed: contention_pass,
            expected: "selected contention profile proves only its configured pool state".to_owned(),
            observed: targeted_contention.as_ref().map_or_else(
                || "not selected".to_owned(),
                |contention| format!(
                    "mode={}, active={}, queued={}",
                    contention.mode.mode,
                    contention.mode.maximum_observed_active_leases,
                    contention.mode.maximum_observed_queue_depth,
                ),
            ),
        },
        Check {
            name: "targeted_profile_prepared_cache_reuse_pass".to_owned(),
            passed: cache_reuse_pass,
            expected: "same-key reuse is directly observed when enabled; disabled control retains no reusable cache entry".to_owned(),
            observed: preparation_cache_reuse.as_ref().map_or_else(
                || "not selected".to_owned(),
                |probe| format!(
                    "enabled={}, status={}, second_prepare_micros={:?}, same_handle={:?}, entries={}",
                    probe.cache_enabled,
                    probe.status,
                    probe.second_prepare_micros,
                    probe.same_prepared_handle,
                    probe.cache_entries_after_probe,
                ),
            ),
        },
        Check {
            name: "targeted_profile_topology_is_constant".to_owned(),
            passed: topology_pass,
            expected: "fixed process/socket/worker/cell topology across selected workload".to_owned(),
            observed: topology_snapshot_range(&topology_snapshots),
        },
        Check {
            name: "targeted_profile_release_clears_prepared_state".to_owned(),
            passed: cache_after_release.entries == 0
                && cache_after_release.source_bytes == 0
                && resources_are_reclaimed(&runtime_resources(&resources_after_release))
                && pool_is_clean(&pool_after_release, config.pool_capacity),
            expected: "no reusable cache entry, backend resource, or pool lease remains after release".to_owned(),
            observed: format!(
                "cache={cache_after_release:?}, backend={:?}, pool={pool_after_release:?}",
                runtime_resources(&resources_after_release)
            ),
        },
    ];
    if workload == ProfileWorkload::ColdPreparation {
        checks.push(Check {
            name: "targeted_profile_cold_preparation_has_no_activation".to_owned(),
            passed: samples.is_empty(),
            expected: "zero activation samples; profile boundary stops after preparation".to_owned(),
            observed: samples.len().to_string(),
        });
    }

    let mut distributions = BTreeMap::new();
    for scenario in &selected_scenarios {
        insert_scenario_distribution(&mut distributions, &samples, scenario);
    }
    insert_phase_distributions(&mut distributions, &samples);
    let payload_flow = PayloadFlowReport {
        input_bytes_submitted_to_typed_call: samples
            .iter()
            .fold(0_u64, |total, sample| total.saturating_add(sample.input_bytes)),
        output_bytes_returned_from_typed_call: samples.iter().fold(0_u64, |total, sample| {
            total.saturating_add(sample.output_bytes.unwrap_or(0))
        }),
        copy_bytes_claimed: 0,
    };
    let mut process_snapshots = Vec::with_capacity(samples.len().saturating_add(2));
    process_snapshots.push(prepared_process);
    process_snapshots.extend(samples.iter().map(|sample| sample.process_after.clone()));
    process_snapshots.push(post_release);
    Ok(TargetedAsyncRunResult {
        artifact: ArtifactReport {
            collector,
            capsule_path,
            capsule_digest,
            capsule_bytes,
            component_path: loaded.component_path.display().to_string(),
            component_digest: loaded.artifact.manifest.component_digest.0,
            component_bytes: loaded.component_bytes,
        },
        validation_micros: preparation_timings.capsule_validation_and_load_micros,
        engine_micros: preparation_timings.wasmtime_engine_construction_micros,
        preparation_micros: preparation_timings.component_preparation_micros,
        first_invocation_ready_micros,
        prepared_release_micros,
        preparation_cache_reuse,
        activation_throughput,
        targeted_contention,
        activation_samples: samples,
        process_snapshots,
        topology_snapshots,
        selected_scenarios,
        payload_flow,
        checks,
        distributions,
    })
}

async fn run_async(
    cli: &Cli,
    config: &EffectiveConfig,
    pool: Arc<FixedCellPool>,
    workers: RuntimeWorkerMonitor,
    before_component_load: TopologySnapshot,
    process_entry: Instant,
) -> Result<AsyncRunResult, BenchError> {
    let collector = latentd::phase0_collector::native_collector_identity("phase0-baseline")
        .map_err(BenchError::new)?;
    let (capsule_path, capsule_digest, capsule_bytes) = capsule_identity(&cli.capsule)?;
    let executable_harness = load_executable_harness_probe(&cli.executable_harness_probe, config)?;

    let prepared_backend = phase0_composition::prepare_phase0_backend(
        &Phase0PreparationConfig {
            capsule: cli.capsule.clone(),
            component: None,
            component_maximum_bytes: COMPONENT_MAXIMUM_BYTES,
            prepared_cache_maximum_entries: PREPARED_CACHE_MAXIMUM_ENTRIES,
            prepared_cache_maximum_bytes: PREPARED_CACHE_MAXIMUM_BYTES,
            prepared_cache_enabled: config.prepared_cache_enabled,
            invocation_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            invocation_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            retained_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            retained_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            requested_memory_bytes: config.memory_bytes.max(config.memory_pressure_bytes),
            requested_fuel: config.fuel,
            wasmtime_instance_allocator: config.wasmtime_allocator.into(),
            wasmtime_copy_on_write_images: config.wasmtime_copy_on_write_images,
            wasmtime_pooling_maximum_instances: config.pool_capacity,
        },
    )
    .await
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0PreparedBackend {
        loaded,
        backend,
        preparation_key,
        prepared,
        cache_after_prepare,
        timings: preparation_timings,
    } = prepared_backend;
    let validation_micros = preparation_timings.capsule_validation_and_load_micros;
    let engine_micros = preparation_timings.wasmtime_engine_construction_micros;
    let preparation_micros = preparation_timings.component_preparation_micros;
    let preparation_cache_reuse = observe_prepared_cache_reuse(
        &backend,
        &loaded.artifact,
        &preparation_key,
        &prepared,
        preparation_micros,
        config.prepared_cache_enabled,
    )
    .await?;

    let timings = PhaseTimingRecorder::default();
    let throughput_saturation_gate = ThroughputSaturationGate::new();
    let pool_for_runner: Arc<dyn CellPool> = Arc::new(TimingCellPool::new(
        Arc::clone(&pool),
        timings.clone(),
        throughput_saturation_gate.clone(),
    ));
    let backend_for_runner: Arc<dyn ExecutionBackend> = Arc::new(TimingExecutionBackend::new(
        Arc::clone(&backend),
        timings.clone(),
    ));
    let runner = phase0_composition::create_phase0_activation_runner(
        pool_for_runner,
        backend_for_runner,
        prepared.clone(),
    )
    .map_err(platform_error)?;
    let first_invocation_ready_micros = elapsed_micros(process_entry);
    let prepared_process = observe_process("after_component_preparation", process_entry);
    let after_component_preparation = TopologySnapshot {
        label: "after_component_preparation".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: prepared_process.clone(),
        pool: pool_snapshot(&pool.observations()),
    };

    let mut checks = Vec::new();
    checks.push(Check {
        name: "real_issue23_executable_probe_passed".to_owned(),
        passed: executable_harness.samples.len() >= 3
            && executable_harness.samples.iter().all(|sample| {
                sample.shutdown_clean
                    && sample.topology_unchanged
                    && sample.output_utf8 == "phase0 executable cold echo"
                    && sample.runtime_workers == config.runtime_workers
                    && sample.pool_capacity == config.pool_capacity
                    && sample.listener_socket_count == 0
            }),
        expected: "at least three successful fresh-process calls through latentd phase0-spike with clean shutdown and unchanged topology".to_owned(),
        observed: format!("{} fresh process samples", executable_harness.samples.len()),
    });
    checks.push(Check {
        name: "real_issue23_executable_failure_and_recovery_probe_passed".to_owned(),
        passed: executable_failure_and_recovery_probe_is_healthy(
            &executable_harness.failure_recovery_samples,
        ),
        expected: "exact issue-23 executable probes cover trap, timeout, and same-composition post-trap recovery".to_owned(),
        observed: format!(
            "{} failure/recovery executable samples",
            executable_harness.failure_recovery_samples.len()
        ),
    });
    checks.push(Check {
        name: "linux_process_resource_probe_supported".to_owned(),
        passed: prepared_process.probe_supported,
        expected: "Linux /proc resource probe available".to_owned(),
        observed: if prepared_process.probe_supported {
            "supported".to_owned()
        } else {
            prepared_process.notes.join("; ")
        },
    });
    checks.push(Check {
        name: "configured_runtime_workers_observed_before_and_after_loading".to_owned(),
        passed: before_component_load.observed_runtime_workers == config.runtime_workers
            && after_component_preparation.observed_runtime_workers == config.runtime_workers,
        expected: config.runtime_workers.to_string(),
        observed: format!(
            "before={}, after={}",
            before_component_load.observed_runtime_workers,
            after_component_preparation.observed_runtime_workers
        ),
    });
    checks.push(Check {
        name: "prepared_cache_bounded_after_prepare".to_owned(),
        passed: if config.prepared_cache_enabled {
            cache_after_prepare.entries == 1
                && cache_after_prepare.source_bytes <= cache_after_prepare.maximum_source_bytes
                && cache_after_prepare.entries <= cache_after_prepare.maximum_entries
        } else {
            cache_after_prepare.entries == 0 && cache_after_prepare.source_bytes == 0
        },
        expected: if config.prepared_cache_enabled {
            "one retained entry within configured entry and byte limits".to_owned()
        } else {
            "cache-disabled run retains no reusable prepared-cache entry".to_owned()
        },
        observed: format!(
            "entries={}, source_bytes={}, maximum_entries={}, maximum_source_bytes={}",
            cache_after_prepare.entries,
            cache_after_prepare.source_bytes,
            cache_after_prepare.maximum_entries,
            cache_after_prepare.maximum_source_bytes
        ),
    });
    checks.push(Check {
        name: "prepared_cache_reuse_probe_matches_configuration".to_owned(),
        passed: if preparation_cache_reuse.cache_enabled {
            preparation_cache_reuse.status == "cache_hit"
                && preparation_cache_reuse.second_prepare_micros.is_some()
                && preparation_cache_reuse.same_prepared_handle == Some(true)
                && preparation_cache_reuse.cache_entries_after_probe == 1
        } else {
            preparation_cache_reuse.status == "disabled_cold_control"
                && preparation_cache_reuse.second_prepare_micros.is_none()
                && preparation_cache_reuse.same_prepared_handle.is_none()
                && preparation_cache_reuse.cache_entries_after_probe == 0
        },
        expected: "enabled cache has a direct same-key handle hit; disabled control has no reusable cache entry".to_owned(),
        observed: format!(
            "enabled={}, status={}, first_prepare_micros={}, second_prepare_micros={:?}, same_handle={:?}, entries={}",
            preparation_cache_reuse.cache_enabled,
            preparation_cache_reuse.status,
            preparation_cache_reuse.first_prepare_micros,
            preparation_cache_reuse.second_prepare_micros,
            preparation_cache_reuse.same_prepared_handle,
            preparation_cache_reuse.cache_entries_after_probe,
        ),
    });

    let pool_probe = run_pool_probe(config, Arc::clone(&pool)).await?;
    checks.push(Check {
        name: "fixed_pool_queue_saturation_is_bounded".to_owned(),
        passed: pool_probe.overflow_rejected
            && pool_probe.maximum_observed_active_leases == config.pool_capacity
            && pool_probe.maximum_observed_queue_depth == config.pool_queue_capacity,
        expected: format!(
            "active={}, queued={}, then one additional waiter rejected",
            config.pool_capacity, config.pool_queue_capacity
        ),
        observed: format!(
            "active={}, queued={}, overflow_rejected={}, error_code={}",
            pool_probe.maximum_observed_active_leases,
            pool_probe.maximum_observed_queue_depth,
            pool_probe.overflow_rejected,
            pool_probe
                .overflow_error_code
                .as_deref()
                .unwrap_or("none")
        ),
    });
    checks.push(Check {
        name: "fixed_pool_returns_to_configured_idle_state".to_owned(),
        passed: pool_is_clean(&pool_probe.final_state, config.pool_capacity),
        expected: format!(
            "capacity={}, available={}, active=0, queued=0, quarantined=0",
            config.pool_capacity, config.pool_capacity
        ),
        observed: format!("{:?}", pool_probe.final_state),
    });

    let mut samples = Vec::new();
    samples.push(
        invoke_case(
            &loaded.artifact.manifest,
            &pool,
            &backend,
            &runner,
            &timings,
            &workers,
            process_entry,
            InvocationRequest {
                scenario: "retained_first_echo",
                iteration: 0,
                input: "phase0 retained first echo",
                expected: ExpectedOutcome::Success,
                memory_bytes: config.memory_bytes,
                fuel: config.fuel,
                timeout_ms: 1_000,
                cancel_after_ms: None,
            },
        )
        .await?,
    );

    for iteration in 0..config.warm_samples {
        samples.push(
            invoke_case(
                &loaded.artifact.manifest,
                &pool,
                &backend,
                &runner,
                &timings,
                &workers,
                process_entry,
                InvocationRequest {
                    scenario: "warm_echo",
                    iteration,
                    input: "phase0 warm echo",
                    expected: ExpectedOutcome::Success,
                    memory_bytes: config.memory_bytes,
                    fuel: config.fuel,
                    timeout_ms: 1_000,
                    cancel_after_ms: None,
                },
            )
            .await?,
        );
    }

    for iteration in 0..config.sequence_repetitions {
        append_mixed_sequence(
            config,
            &loaded.artifact.manifest,
            &pool,
            &backend,
            &runner,
            &timings,
            &workers,
            process_entry,
            iteration,
            &mut samples,
        )
        .await?;
    }

    let activation_throughput = run_activation_throughput(
        config,
        &loaded.artifact.manifest,
        &pool,
        &backend,
        &runner,
        &timings,
        &throughput_saturation_gate,
        &workers,
        process_entry,
        &mut samples,
    )
    .await?;
    checks.push(Check {
        name: "real_activation_throughput_reaches_pool_capacity".to_owned(),
        passed: activation_throughput
            .at_capacity
            .maximum_observed_active_leases
            == config.pool_capacity
            && activation_throughput
                .at_capacity
                .maximum_observed_queue_depth
                == 0,
        expected: format!(
            "active={} and queued=0 during complete runner/backend activations",
            config.pool_capacity
        ),
        observed: format!(
            "active={}, queued={}",
            activation_throughput
                .at_capacity
                .maximum_observed_active_leases,
            activation_throughput
                .at_capacity
                .maximum_observed_queue_depth,
        ),
    });
    checks.push(Check {
        name: "real_activation_throughput_reaches_bounded_queue_saturation".to_owned(),
        passed: activation_throughput
            .bounded_queue_saturation
            .maximum_observed_active_leases
            == config.pool_capacity
            && activation_throughput
                .bounded_queue_saturation
                .maximum_observed_queue_depth
                == config.pool_queue_capacity
            && activation_throughput
                .bounded_queue_saturation
                .queued_acquire_wait_micros
                .is_some(),
        expected: format!(
            "active={} and queued={} during complete runner/backend activations",
            config.pool_capacity, config.pool_queue_capacity
        ),
        observed: format!(
            "active={}, queued={}, queued_distribution={}",
            activation_throughput
                .bounded_queue_saturation
                .maximum_observed_active_leases,
            activation_throughput
                .bounded_queue_saturation
                .maximum_observed_queue_depth,
            activation_throughput
                .bounded_queue_saturation
                .queued_acquire_wait_micros
                .is_some()
        ),
    });

    let per_activation_clean = samples.iter().all(|sample| {
        pool_is_clean(&sample.pool_after, config.pool_capacity)
            && sample.runner_after.active_cancellation_registrations == 0
            && sample.runner_after.running_invocations == 0
            && sample.runner_after.quarantined_cells == 0
            && sample.runner_after.disposition_failures == 0
            && resources_are_reclaimed(&sample.backend_resources_after)
            && sample.retained_log_entries_after_clear == 0
            && if config.prepared_cache_enabled {
                sample.prepared_cache_after.entries == 1
                    && sample.prepared_cache_after.source_bytes == cache_after_prepare.source_bytes
            } else {
                sample.prepared_cache_after.entries == 0
                    && sample.prepared_cache_after.source_bytes == 0
            }
    });
    checks.push(Check {
        name: "activation_owned_state_returns_to_baseline_after_every_sample".to_owned(),
        passed: per_activation_clean,
        expected: "no active lease, waiter, cancellation registration, invocation, store, host state, instance, temporary buffer, cancellation probe, retained log, quarantine, or cache growth".to_owned(),
        observed: if per_activation_clean {
            format!("{} samples clean", samples.len())
        } else {
            "one or more raw activation samples contain non-baseline state".to_owned()
        },
    });

    let expected_outcomes_pass = samples.iter().all(|sample| {
        sample.outcome.name == sample.expected_outcome && sample.contract_result_valid
    });
    checks.push(Check {
        name: "all_scenarios_return_expected_terminal_outcomes".to_owned(),
        passed: expected_outcomes_pass,
        expected: "success/domain_error/trap/timeout/cancelled/resource_exhausted as requested".to_owned(),
        observed: outcome_summary(&samples),
    });

    let recovery_pass = cause_specific_failure_recovery_is_healthy(&samples);
    checks.push(Check {
        name: "failure_does_not_degrade_the_next_cause_specific_echo".to_owned(),
        passed: recovery_pass,
        expected: "every failure is immediately followed by a distinctly labelled successful recovery echo".to_owned(),
        observed: if recovery_pass {
            "all cause-specific recovery echoes succeeded".to_owned()
        } else {
            "one or more failure/recovery pairs were incomplete or unhealthy".to_owned()
        },
    });

    let timeout_overshoots = scenario_values(&samples, "timeout", |sample| {
        sample.timeout_or_cancel_overshoot_micros.unwrap_or(0)
    });
    let cancellation_overshoots = scenario_values(&samples, "cancellation", |sample| {
        sample.timeout_or_cancel_overshoot_micros.unwrap_or(0)
    });
    let maximum_overshoot_micros = config.maximum_overshoot_ms.saturating_mul(1_000);
    let overshoot_pass = timeout_overshoots
        .iter()
        .chain(&cancellation_overshoots)
        .all(|value| *value <= maximum_overshoot_micros);
    checks.push(Check {
        name: "timeout_and_cancellation_overshoot_are_bounded".to_owned(),
        passed: overshoot_pass,
        expected: format!("each overshoot <= {maximum_overshoot_micros} microseconds"),
        observed: format!(
            "timeout_max={}us, cancellation_max={}us",
            timeout_overshoots.iter().copied().max().unwrap_or(0),
            cancellation_overshoots.iter().copied().max().unwrap_or(0)
        ),
    });

    let mut topology_snapshots = vec![
        before_component_load.clone(),
        after_component_preparation.clone(),
    ];
    topology_snapshots.extend(samples.iter().map(|sample| TopologySnapshot {
        label: sample.process_after.label.clone(),
        observed_runtime_workers: sample.observed_runtime_workers_after,
        process: sample.process_after.clone(),
        pool: sample.pool_after.clone(),
    }));
    let topology_pass = topology_is_constant(
        &before_component_load,
        &after_component_preparation,
        &topology_snapshots[2..],
        config,
    );
    checks.push(Check {
        name: "topology_constant_across_component_loading_and_repeated_invocations".to_owned(),
        passed: topology_pass,
        expected: format!(
            "process/socket/listener/cell topology constant, runtime workers={}, and one bounded Wasmtime epoch thread after preparation",
            config.runtime_workers
        ),
        observed: topology_snapshot_range(&topology_snapshots),
    });

    let steady_snapshots = samples
        .iter()
        .map(|sample| sample.process_after.clone())
        .collect::<Vec<_>>();
    let rss_values = steady_snapshots
        .iter()
        .filter_map(|snapshot| snapshot.rss_bytes)
        .collect::<Vec<_>>();
    let rss_analysis = bounded_growth(&rss_values, config.rss_growth_allowance_bytes);
    checks.push(Check {
        name: "rss_has_no_unbounded_monotonic_growth".to_owned(),
        passed: rss_analysis.passed,
        expected: format!(
            "steady-state range and net growth <= {} bytes",
            config.rss_growth_allowance_bytes
        ),
        observed: rss_analysis.description,
    });

    let fd_values = steady_snapshots
        .iter()
        .filter_map(|snapshot| snapshot.file_descriptor_count)
        .collect::<Vec<_>>();
    let fd_analysis = bounded_growth(&fd_values, config.fd_growth_allowance);
    checks.push(Check {
        name: "file_descriptors_have_no_unbounded_monotonic_growth".to_owned(),
        passed: fd_analysis.passed,
        expected: format!(
            "steady-state range and net growth <= {} descriptors",
            config.fd_growth_allowance
        ),
        observed: fd_analysis.description,
    });

    let release_started = Instant::now();
    backend
        .release(prepared)
        .await
        .map_err(platform_error)?;
    let prepared_release_micros = duration_micros(release_started.elapsed());
    backend.log_sink().clear();
    let cache_after_release = backend.cache_snapshot();
    let resources_after_release = backend.resource_snapshot();
    let pool_after_release = pool_snapshot(&pool.observations());
    let post_release = observe_process("prepared_component_released", process_entry);
    checks.push(Check {
        name: "explicit_release_clears_prepared_cache".to_owned(),
        passed: cache_after_release.entries == 0 && cache_after_release.source_bytes == 0,
        expected: "entries=0 and source_bytes=0".to_owned(),
        observed: format!(
            "entries={}, source_bytes={}",
            cache_after_release.entries, cache_after_release.source_bytes
        ),
    });
    checks.push(Check {
        name: "post_release_backend_and_pool_are_clean".to_owned(),
        passed: resources_are_reclaimed(&runtime_resources(&resources_after_release))
            && pool_is_clean(&pool_after_release, config.pool_capacity),
        expected: "all live backend resources zero and fixed pool fully available".to_owned(),
        observed: format!(
            "backend={:?}, pool={:?}",
            runtime_resources(&resources_after_release),
            pool_after_release
        ),
    });

    let mut process_snapshots = Vec::with_capacity(samples.len() + 2);
    process_snapshots.push(prepared_process);
    process_snapshots.extend(steady_snapshots);
    process_snapshots.push(post_release.clone());
    topology_snapshots.push(TopologySnapshot {
        label: "prepared_component_released".to_owned(),
        observed_runtime_workers: workers.active_workers(),
        process: post_release,
        pool: pool_after_release,
    });

    let mut distributions = BTreeMap::new();
    distributions.insert(
        "process_launch_to_completion_real_executable_micros".to_owned(),
        executable_harness
            .process_launch_to_completion_micros
            .clone(),
    );
    distributions.insert(
        "cold_echo_elapsed_micros".to_owned(),
        executable_harness.cold_activation_micros.clone(),
    );
    for scenario in [
        "retained_first_echo",
        "warm_echo",
        "domain_error",
        "trap",
        "timeout",
        "cancellation",
        "memory_pressure",
        "recovery_after_domain_error",
        "recovery_after_trap",
        "recovery_after_timeout",
        "recovery_after_cancellation",
        "recovery_after_memory_pressure",
        "throughput_at_capacity",
        "throughput_bounded_queue_saturation",
    ] {
        insert_scenario_distribution(&mut distributions, &samples, scenario);
    }
    insert_phase_distributions(&mut distributions, &samples);
    if let Some(distribution) = distribution(&timeout_overshoots) {
        distributions.insert("timeout_overshoot_micros".to_owned(), distribution);
    }
    if let Some(distribution) = distribution(&cancellation_overshoots) {
        distributions.insert("cancellation_overshoot_micros".to_owned(), distribution);
    }

    Ok(AsyncRunResult {
        artifact: ArtifactReport {
            collector,
            capsule_path,
            capsule_digest,
            capsule_bytes,
            component_path: loaded.component_path.display().to_string(),
            component_digest: loaded.artifact.manifest.component_digest.0,
            component_bytes: loaded.component_bytes,
        },
        executable_harness,
        validation_micros,
        engine_micros,
        preparation_micros,
        first_invocation_ready_micros,
        prepared_release_micros,
        preparation_cache_reuse,
        pool_probe,
        activation_throughput,
        activation_samples: samples,
        process_snapshots,
        topology_snapshots,
        checks,
        distributions,
    })
}

fn capsule_identity(capsule: &Path) -> Result<(String, String, u64), BenchError> {
    let manifest_path = if capsule.is_dir() {
        capsule.join("capsule.json")
    } else {
        capsule.to_path_buf()
    };
    let (_, path, digest, byte_count) =
        read_fixture_identity(&manifest_path, "capsule manifest")?;
    Ok((path, digest, byte_count))
}

fn read_fixture_identity(
    path: &Path,
    fixture_name: &str,
) -> Result<(Vec<u8>, String, String, u64), BenchError> {
    let bytes = fs::read(path).map_err(|error| {
        BenchError::new(format!(
            "failed to read {fixture_name} for fixture identity ({}): {error}",
            path.display()
        ))
    })?;
    let byte_count = u64::try_from(bytes.len())
        .map_err(|_| BenchError::new(format!("{fixture_name} is too large to record")))?;
    if byte_count == 0 {
        return Err(BenchError::new(format!(
            "{fixture_name} is empty and cannot identify the measured fixture"
        )));
    }
    let digest = Sha256::digest(&bytes);
    Ok((bytes, path.display().to_string(), format!("sha256:{digest:x}"), byte_count))
}

#[allow(clippy::too_many_arguments)]
async fn append_mixed_sequence(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    timings: &PhaseTimingRecorder,
    workers: &RuntimeWorkerMonitor,
    process_entry: Instant,
    iteration: u32,
    samples: &mut Vec<ActivationSample>,
) -> Result<(), BenchError> {
    let cases = [
        InvocationRequest {
            scenario: "sequence_echo",
            iteration,
            input: "sequence healthy echo",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "domain_error",
            iteration,
            input: "",
            expected: ExpectedOutcome::DomainError,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "recovery_after_domain_error",
            iteration,
            input: "healthy after domain error",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "trap",
            iteration,
            input: FIXTURE_TRAP,
            expected: ExpectedOutcome::Trap,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "recovery_after_trap",
            iteration,
            input: "healthy after trap",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "timeout",
            iteration,
            input: FIXTURE_INFINITE,
            expected: ExpectedOutcome::Timeout,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: config.timeout_ms,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "recovery_after_timeout",
            iteration,
            input: "healthy after timeout",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "cancellation",
            iteration,
            input: FIXTURE_INFINITE,
            expected: ExpectedOutcome::Cancelled,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: Some(config.cancel_after_ms),
        },
        InvocationRequest {
            scenario: "recovery_after_cancellation",
            iteration,
            input: "healthy after cancellation",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "memory_pressure",
            iteration,
            input: FIXTURE_MEMORY,
            expected: ExpectedOutcome::ResourceExhausted,
            memory_bytes: config.memory_pressure_bytes,
            fuel: config.fuel,
            timeout_ms: 2_000,
            cancel_after_ms: None,
        },
        InvocationRequest {
            scenario: "recovery_after_memory_pressure",
            iteration,
            input: "healthy after memory pressure",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
    ];

    for request in cases {
        samples.push(
            invoke_case(
                manifest,
                pool,
                backend,
                runner,
                timings,
                workers,
                process_entry,
                request,
            )
            .await?,
        );
    }
    Ok(())
}

fn load_executable_harness_probe(
    path: &Path,
    config: &EffectiveConfig,
) -> Result<ExecutableHarnessProbeReport, BenchError> {
    let bytes = fs::read(path).map_err(|error| {
        BenchError::new(format!(
            "failed to read executable harness probe {}: {error}",
            path.display()
        ))
    })?;
    let document: ExecutableHarnessProbeDocument = serde_json::from_slice(&bytes)?;
    if document.schema_version != EXECUTABLE_PROBE_SCHEMA_VERSION {
        return Err(BenchError::new(format!(
            "unexpected executable probe schema {}",
            document.schema_version
        )));
    }
    if document.samples.len() < 3 {
        return Err(BenchError::new(
            "executable harness probe requires at least three independent cold samples",
        ));
    }
    for sample in &document.samples {
        if !sample.shutdown_clean
            || !sample.topology_unchanged
            || sample.output_utf8 != "phase0 executable cold echo"
            || sample.runtime_workers != config.runtime_workers
            || sample.pool_capacity != config.pool_capacity
            || sample.listener_socket_count != 0
        {
            return Err(BenchError::new(format!(
                "issue-23 executable probe sample {} failed parity validation",
                sample.iteration
            )));
        }
    }
    if !executable_failure_and_recovery_probe_is_healthy(&document.failure_recovery_samples) {
        return Err(BenchError::new(
            "issue-23 executable failure/recovery probe did not prove trap, timeout, and post-failure recovery",
        ));
    }
    let launch_values = document
        .samples
        .iter()
        .map(|sample| sample.launch_to_completion_micros)
        .collect::<Vec<_>>();
    let cold_values = document
        .samples
        .iter()
        .map(|sample| sample.activation_elapsed_micros)
        .collect::<Vec<_>>();
    Ok(ExecutableHarnessProbeReport {
        schema_version: document.schema_version,
        command: document.command,
        process_launch_to_completion_micros: distribution(&launch_values)
            .ok_or_else(|| BenchError::new("executable probe has no launch samples"))?,
        cold_activation_micros: distribution(&cold_values)
            .ok_or_else(|| BenchError::new("executable probe has no cold activation samples"))?,
        samples: document.samples,
        failure_recovery_samples: document.failure_recovery_samples,
    })
}

fn executable_failure_and_recovery_probe_is_healthy(
    samples: &[ExecutableHarnessFailureProbeSample],
) -> bool {
    let find = |scenario: &str| samples.iter().find(|sample| sample.scenario == scenario);
    let clean_topology = |result: &Value| {
        result["shutdown"]["clean"] == Value::Bool(true)
            && result["topology"]["unchanged"] == Value::Bool(true)
    };
    let trap = find("trap");
    let timeout = find("timeout");
    let recovery = find("trap_then_recovery");
    trap.is_some_and(|sample| {
        sample.expected_exit_code == 12
            && sample.exit_code == 12
            && sample.expected_outcome == "trap"
            && sample.raw_result["outcome"] == "trap"
            && clean_topology(&sample.raw_result)
    }) && timeout.is_some_and(|sample| {
        sample.expected_exit_code == 11
            && sample.exit_code == 11
            && sample.expected_outcome == "timeout"
            && sample.raw_result["outcome"] == "timeout"
            && clean_topology(&sample.raw_result)
    }) && recovery.is_some_and(|sample| {
        let activations = sample.raw_result["recovery"]["activations"].as_array();
        sample.expected_exit_code == 0
            && sample.exit_code == 0
            && sample.expected_outcome == "success"
            && sample.raw_result["outcome"] == "success"
            && sample.raw_result["recovery"]["expected_failure"] == "trap"
            && activations.is_some_and(|activations| {
                activations.len() == 2
                    && activations[0]["phase"] == "trap"
                    && activations[0]["activation"]["outcome"] == "trap"
                    && activations[1]["phase"] == "recovery"
                    && activations[1]["activation"]["outcome"] == "success"
            })
            && clean_topology(&sample.raw_result)
    })
}

fn cause_specific_failure_recovery_is_healthy(samples: &[ActivationSample]) -> bool {
    let expected_pairs = [
        ("domain_error", "recovery_after_domain_error"),
        ("trap", "recovery_after_trap"),
        ("timeout", "recovery_after_timeout"),
        ("cancellation", "recovery_after_cancellation"),
        ("memory_pressure", "recovery_after_memory_pressure"),
    ];
    for (index, sample) in samples.iter().enumerate() {
        if let Some((_, expected_recovery)) = expected_pairs
            .iter()
            .find(|(failure, _)| *failure == sample.scenario)
        {
            let Some(next) = samples.get(index.saturating_add(1)) else {
                return false;
            };
            if next.scenario != *expected_recovery
                || next.outcome.name != "success"
                || !next.contract_result_valid
            {
                return false;
            }
        }
    }
    true
}

fn topology_is_constant(
    before: &TopologySnapshot,
    prepared: &TopologySnapshot,
    workloads: &[TopologySnapshot],
    config: &EffectiveConfig,
) -> bool {
    let stable_identity = |snapshot: &TopologySnapshot| {
        snapshot.process.process_count == before.process.process_count
            && snapshot.process.open_socket_count == before.process.open_socket_count
            && snapshot.process.listening_socket_count == before.process.listening_socket_count
            && snapshot.observed_runtime_workers == config.runtime_workers
            && pool_is_clean(&snapshot.pool, config.pool_capacity)
    };
    let prepared_thread_delta_is_bounded = match (
        before.process.thread_count,
        prepared.process.thread_count,
    ) {
        (Some(before_threads), Some(prepared_threads)) => {
            prepared_threads >= before_threads
                && prepared_threads <= before_threads.saturating_add(1)
        }
        _ => false,
    };
    let steady_threads = workloads.iter().all(|snapshot| {
        snapshot.process.thread_count == prepared.process.thread_count
    });
    stable_identity(before)
        && stable_identity(prepared)
        && workloads.iter().all(stable_identity)
        && prepared_thread_delta_is_bounded
        && steady_threads
}

fn topology_snapshot_range(snapshots: &[TopologySnapshot]) -> String {
    let worker_min = snapshots
        .iter()
        .map(|snapshot| snapshot.observed_runtime_workers)
        .min()
        .unwrap_or(0);
    let worker_max = snapshots
        .iter()
        .map(|snapshot| snapshot.observed_runtime_workers)
        .max()
        .unwrap_or(0);
    let process_min = snapshots
        .iter()
        .map(|snapshot| snapshot.process.process_count)
        .min()
        .unwrap_or(0);
    let process_max = snapshots
        .iter()
        .map(|snapshot| snapshot.process.process_count)
        .max()
        .unwrap_or(0);
    let active_max = snapshots
        .iter()
        .map(|snapshot| snapshot.pool.active_leases)
        .max()
        .unwrap_or(0);
    let queue_max = snapshots
        .iter()
        .map(|snapshot| snapshot.pool.queue_depth)
        .max()
        .unwrap_or(0);
    format!(
        "workers={worker_min}..{worker_max}, processes={process_min}..{process_max}, completed-snapshot active_max={active_max}, queue_max={queue_max}, {}",
        topology_range(
            &snapshots
                .iter()
                .map(|snapshot| snapshot.process.clone())
                .collect::<Vec<_>>()
        )
    )
}

fn insert_phase_distributions(
    distributions: &mut BTreeMap<String, Distribution>,
    samples: &[ActivationSample],
) {
    let metrics: [(&str, fn(&ActivationPhaseTimingReport) -> u64); 14] = [
        ("acquire_or_queue_wait_micros", |value| value.acquire_or_queue_wait_micros),
        ("contained_execution_micros", |value| value.contained_execution_micros),
        ("backend_setup_micros", |value| value.backend_setup_micros),
        ("guest_call_micros", |value| value.guest_call_micros),
        ("host_call_micros", |value| value.host_call_micros),
        ("component_post_return_micros", |value| value.component_post_return_micros),
        (
            "activation_resource_reclamation_micros",
            |value| value.activation_resource_reclamation_micros,
        ),
        (
            "outcome_classification_micros",
            |value| value.outcome_classification_micros,
        ),
        ("reusable_proof_micros", |value| value.reusable_proof_micros),
        ("backend_total_micros", |value| value.backend_total_micros),
        ("backend_resource_cleanup_micros", |value| value.backend_resource_cleanup_micros),
        ("cell_disposition_micros", |value| value.cell_disposition_micros),
        ("post_invocation_cleanup_micros", |value| value.post_invocation_cleanup_micros),
        ("total_invocation_micros", |value| value.total_invocation_micros),
    ];
    for (name, extractor) in metrics {
        let values = samples
            .iter()
            .map(|sample| extractor(&sample.phase_timings))
            .collect::<Vec<_>>();
        if let Some(distribution) = distribution(&values) {
            distributions.insert(name.to_owned(), distribution);
        }
    }
}

fn now_unix_micros() -> u64 {
    let micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros();
    u64::try_from(micros).unwrap_or(u64::MAX)
}
