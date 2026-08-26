fn run(cli: Cli, process_entry: Instant) -> Result<bool, BenchError> {
    let config = EffectiveConfig::from_cli(&cli)?;
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

async fn run_async(
    cli: &Cli,
    config: &EffectiveConfig,
    pool: Arc<FixedCellPool>,
    workers: RuntimeWorkerMonitor,
    before_component_load: TopologySnapshot,
    process_entry: Instant,
) -> Result<AsyncRunResult, BenchError> {
    let executable_harness = load_executable_harness_probe(
        &cli.executable_harness_probe,
        config,
    )?;

    let prepared_backend = phase0_composition::prepare_phase0_backend(
        &Phase0PreparationConfig {
            capsule: cli.capsule.clone(),
            component: None,
            component_maximum_bytes: COMPONENT_MAXIMUM_BYTES,
            prepared_cache_maximum_entries: PREPARED_CACHE_MAXIMUM_ENTRIES,
            prepared_cache_maximum_bytes: PREPARED_CACHE_MAXIMUM_BYTES,
            invocation_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            invocation_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            retained_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            retained_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            requested_memory_bytes: config.memory_bytes.max(config.memory_pressure_bytes),
            requested_fuel: config.fuel,
        },
    )
    .await
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0PreparedBackend {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        timings: preparation_timings,
    } = prepared_backend;
    let validation_micros = preparation_timings.capsule_validation_and_load_micros;
    let engine_micros = preparation_timings.wasmtime_engine_construction_micros;
    let preparation_micros = preparation_timings.component_preparation_micros;

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
        passed: cache_after_prepare.entries == 1
            && cache_after_prepare.source_bytes <= cache_after_prepare.maximum_source_bytes
            && cache_after_prepare.entries <= cache_after_prepare.maximum_entries,
        expected: "one retained entry within configured entry and byte limits".to_owned(),
        observed: format!(
            "entries={}, source_bytes={}, maximum_entries={}, maximum_source_bytes={}",
            cache_after_prepare.entries,
            cache_after_prepare.source_bytes,
            cache_after_prepare.maximum_entries,
            cache_after_prepare.maximum_source_bytes
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
            && sample.prepared_cache_after.entries == 1
            && sample.prepared_cache_after.source_bytes == cache_after_prepare.source_bytes
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
            capsule_path: cli.capsule.display().to_string(),
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
        pool_probe,
        activation_throughput,
        activation_samples: samples,
        process_snapshots,
        topology_snapshots,
        checks,
        distributions,
    })
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
    let document: ExecutableHarnessProbeDocument =
        serde_json::from_slice(&fs::read(path)?)?;
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
