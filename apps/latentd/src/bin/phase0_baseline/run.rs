async fn run_async(
    cli: &Cli,
    config: &EffectiveConfig,
    pool: Arc<FixedCellPool>,
    process_entry: Instant,
) -> Result<AsyncRunResult, BenchError> {
    let validation_started = Instant::now();
    let loaded = load_artifact(&cli.capsule)?;
    validate_requested_budgets(config, &loaded.artifact.manifest)?;
    let validation_micros = duration_micros(validation_started.elapsed());

    let declared = &loaded.artifact.manifest.execution.resource_budget_ceiling;
    let engine_started = Instant::now();
    let factory = Phase0WasmtimeEngineFactory::new(Phase0WasmtimeConfig {
        maximum_component_bytes: COMPONENT_MAXIMUM_BYTES,
        maximum_memory_bytes: declared.memory_bytes,
        maximum_fuel: declared.cpu_fuel,
        prepared_cache_maximum_entries: PREPARED_CACHE_MAXIMUM_ENTRIES,
        prepared_cache_maximum_source_bytes: PREPARED_CACHE_MAXIMUM_BYTES,
        invocation_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
        invocation_log_maximum_bytes: LOG_MAXIMUM_BYTES,
        retained_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
        retained_log_maximum_bytes: LOG_MAXIMUM_BYTES,
        epoch_tick_interval_millis: EPOCH_TICK_INTERVAL_MILLIS,
        ..Phase0WasmtimeConfig::default()
    })
    .map_err(platform_error)?;
    let preparation_key =
        factory.preparation_key(loaded.artifact.descriptor.release_digest.clone());
    let backend = Arc::new(factory.create_backend_instance());
    drop(factory);
    let engine_micros = duration_micros(engine_started.elapsed());

    let preparation_started = Instant::now();
    let prepared = backend
        .prepare(&loaded.artifact, &preparation_key)
        .await
        .map_err(platform_error)?;
    let preparation_micros = duration_micros(preparation_started.elapsed());
    let cache_after_prepare = backend.cache_snapshot();

    let backend_for_runner: Arc<dyn ExecutionBackend> = backend.clone();
    let pool_for_runner: Arc<dyn CellPool> = pool.clone();
    let runner = Arc::new(
        Phase0ActivationRunner::new(
            Phase0ActivationRunnerConfig::default(),
            pool_for_runner,
            backend_for_runner,
            prepared.clone(),
            bound_imports(),
        )
        .map_err(platform_error)?,
    );
    let first_invocation_ready_micros = elapsed_micros(process_entry);
    let steady_idle = observe_process("prepared_idle", process_entry);

    let mut checks = Vec::new();
    checks.push(Check {
        name: "linux_process_resource_probe_supported".to_owned(),
        passed: steady_idle.probe_supported,
        expected: "Linux /proc resource probe available".to_owned(),
        observed: if steady_idle.probe_supported {
            "supported".to_owned()
        } else {
            steady_idle.notes.join("; ")
        },
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
        passed: pool_probe.overflow_rejected,
        expected: format!(
            "the {} configured waiters are admitted and one additional waiter is rejected",
            config.pool_queue_capacity
        ),
        observed: format!(
            "overflow_rejected={}, error_code={}",
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
    let cold = invoke_case(
        config,
        &loaded.artifact.manifest,
        &pool,
        &backend,
        &runner,
        process_entry,
        InvocationRequest {
            scenario: "cold_echo",
            iteration: 0,
            input: "phase0 cold echo",
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
    )
    .await?;
    samples.push(cold);

    for iteration in 0..config.warm_samples {
        let sample = invoke_case(
            config,
            &loaded.artifact.manifest,
            &pool,
            &backend,
            &runner,
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
        .await?;
        samples.push(sample);
    }

    for iteration in 0..config.sequence_repetitions {
        append_mixed_sequence(
            config,
            &loaded.artifact.manifest,
            &pool,
            &backend,
            &runner,
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
        process_entry,
        &mut samples,
    )
    .await?;

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
        let expected = expected_outcome_for_scenario(&sample.scenario);
        expected.is_none_or(|expected| sample.outcome.name == expected)
            && sample.contract_result_valid
    });
    checks.push(Check {
        name: "all_scenarios_return_expected_terminal_outcomes".to_owned(),
        passed: expected_outcomes_pass,
        expected: "success/domain_error/trap/timeout/cancelled/resource_exhausted as requested".to_owned(),
        observed: outcome_summary(&samples),
    });

    let recovery_pass = failure_recovery_is_healthy(&samples);
    checks.push(Check {
        name: "failure_does_not_degrade_the_next_echo".to_owned(),
        passed: recovery_pass,
        expected: "every failure scenario is immediately followed by a successful recovery echo".to_owned(),
        observed: if recovery_pass {
            "all recovery echoes succeeded".to_owned()
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

    let steady_snapshots = samples
        .iter()
        .map(|sample| sample.process_after.clone())
        .collect::<Vec<_>>();
    let topology_pass = steady_snapshots.iter().all(|snapshot| {
        snapshot.process_count == steady_idle.process_count
            && snapshot.thread_count == steady_idle.thread_count
            && snapshot.open_socket_count == steady_idle.open_socket_count
            && snapshot.listening_socket_count == steady_idle.listening_socket_count
    });
    checks.push(Check {
        name: "process_thread_and_socket_topology_remains_constant".to_owned(),
        passed: topology_pass,
        expected: format!(
            "processes={}, threads={:?}, open_sockets={:?}, listeners={:?}",
            steady_idle.process_count,
            steady_idle.thread_count,
            steady_idle.open_socket_count,
            steady_idle.listening_socket_count
        ),
        observed: topology_range(&steady_snapshots),
    });

    let rss_values = steady_snapshots
        .iter()
        .filter_map(|snapshot| snapshot.rss_bytes)
        .collect::<Vec<_>>();
    let rss_analysis = bounded_growth(&rss_values, config.rss_growth_allowance_bytes);
    checks.push(Check {
        name: "rss_has_no_unbounded_monotonic_growth".to_owned(),
        passed: rss_analysis.passed,
        expected: format!(
            "steady-state range <= {} bytes, or no monotonic growth trend beyond that allowance",
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
            "steady-state range <= {} descriptors, or no monotonic growth trend beyond that allowance",
            config.fd_growth_allowance
        ),
        observed: fd_analysis.description,
    });

    backend
        .release(prepared)
        .await
        .map_err(platform_error)?;
    backend.log_sink().clear();
    tokio::time::sleep(Duration::from_millis(10)).await;
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
    process_snapshots.push(steady_idle);
    process_snapshots.extend(steady_snapshots);
    process_snapshots.push(post_release);

    let mut distributions = BTreeMap::new();
    insert_scenario_distribution(&mut distributions, &samples, "cold_echo");
    insert_scenario_distribution(&mut distributions, &samples, "warm_echo");
    insert_scenario_distribution(&mut distributions, &samples, "domain_error");
    insert_scenario_distribution(&mut distributions, &samples, "trap");
    insert_scenario_distribution(&mut distributions, &samples, "timeout");
    insert_scenario_distribution(&mut distributions, &samples, "cancellation");
    insert_scenario_distribution(&mut distributions, &samples, "memory_pressure");
    insert_scenario_distribution(&mut distributions, &samples, "recovery_echo");
    insert_scenario_distribution(&mut distributions, &samples, "throughput_echo");
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
        validation_micros,
        engine_micros,
        preparation_micros,
        first_invocation_ready_micros,
        pool_probe,
        activation_throughput,
        activation_samples: samples,
        process_snapshots,
        checks,
        distributions,
    })
}

async fn append_mixed_sequence(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
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
            scenario: "recovery_echo",
            iteration: iteration.saturating_mul(10),
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
            scenario: "recovery_echo",
            iteration: iteration.saturating_mul(10).saturating_add(1),
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
            scenario: "recovery_echo",
            iteration: iteration.saturating_mul(10).saturating_add(2),
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
            scenario: "recovery_echo",
            iteration: iteration.saturating_mul(10).saturating_add(3),
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
            scenario: "recovery_echo",
            iteration: iteration.saturating_mul(10).saturating_add(4),
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
                config,
                manifest,
                pool,
                backend,
                runner,
                process_entry,
                request,
            )
            .await?,
        );
    }
    Ok(())
}
