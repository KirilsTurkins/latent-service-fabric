async fn run_pool_probe(
    config: &EffectiveConfig,
    pool: Arc<FixedCellPool>,
) -> Result<PoolProbeReport, BenchError> {
    let tenant = TenantId("phase0-baseline".to_owned());
    let mut acquire_micros = Vec::new();
    let mut release_micros = Vec::new();

    for iteration in 0..config.warm_samples {
        let activation_id = ActivationId(format!("pool-immediate-{iteration:08}"));
        let budget = pool_budget(10_000);
        let acquire_started = Instant::now();
        let lease = pool
            .acquire(
                &activation_id,
                &tenant,
                CellClass::Standard,
                &budget,
            )
            .await
            .map_err(platform_error)?;
        acquire_micros.push(duration_micros(acquire_started.elapsed()));
        let release_started = Instant::now();
        pool.release(lease).await.map_err(platform_error)?;
        release_micros.push(duration_micros(release_started.elapsed()));
    }

    let mut held = Vec::new();
    for slot in 0..config.pool_capacity {
        let activation_id = ActivationId(format!("pool-held-{slot:08}"));
        let budget = pool_budget(10_000);
        held.push(
            pool.acquire(
                &activation_id,
                &tenant,
                CellClass::Standard,
                &budget,
            )
            .await
            .map_err(platform_error)?,
        );
    }
    let maximum_observed_active_leases = pool.observations().active_leases;

    let mut queued = Vec::new();
    for waiter in 0..config.pool_queue_capacity {
        let queued_pool = Arc::clone(&pool);
        queued.push(tokio::spawn(async move {
            let activation_id = ActivationId(format!("pool-queued-{waiter:08}"));
            let tenant = TenantId("phase0-baseline".to_owned());
            let budget = pool_budget(10_000);
            let started = Instant::now();
            let lease = queued_pool
                .acquire(
                    &activation_id,
                    &tenant,
                    CellClass::Standard,
                    &budget,
                )
                .await
                .map_err(platform_error)?;
            let waited = duration_micros(started.elapsed());
            queued_pool.release(lease).await.map_err(platform_error)?;
            Ok::<u64, BenchError>(waited)
        }));
    }
    wait_for_queue_depth(&pool, config.pool_queue_capacity).await?;
    let maximum_observed_queue_depth = pool.observations().queue_depth;

    let overflow_id = ActivationId("pool-overflow".to_owned());
    let overflow_budget = pool_budget(10_000);
    let overflow = pool
        .acquire(
            &overflow_id,
            &tenant,
            CellClass::Standard,
            &overflow_budget,
        )
        .await;
    let (overflow_rejected, overflow_error_code) = match overflow {
        Ok(lease) => {
            pool.release(lease).await.map_err(platform_error)?;
            (false, None)
        }
        Err(error) => (true, Some(platform_error_code_name(error.code).to_owned())),
    };

    for lease in held {
        pool.release(lease).await.map_err(platform_error)?;
        tokio::task::yield_now().await;
    }
    let mut queued_wait_micros = Vec::new();
    for handle in queued {
        queued_wait_micros.push(
            handle
                .await
                .map_err(|error| BenchError::new(format!("queued pool probe task failed: {error}")))??,
        );
    }

    let barrier = Arc::new(Barrier::new(
        usize::try_from(config.pool_capacity)
            .map_err(|_| BenchError::new("pool capacity does not fit usize"))?
            .saturating_add(1),
    ));
    let throughput_started = Instant::now();
    let mut workers = Vec::new();
    for worker in 0..config.pool_capacity {
        let worker_pool = Arc::clone(&pool);
        let worker_barrier = Arc::clone(&barrier);
        let iterations = config.pool_iterations;
        workers.push(tokio::spawn(async move {
            let tenant = TenantId("phase0-baseline".to_owned());
            worker_barrier.wait().await;
            for iteration in 0..iterations {
                let activation_id =
                    ActivationId(format!("pool-throughput-{worker:04}-{iteration:08}"));
                let budget = pool_budget(60_000);
                let lease = worker_pool
                    .acquire(
                        &activation_id,
                        &tenant,
                        CellClass::Standard,
                        &budget,
                    )
                    .await
                    .map_err(platform_error)?;
                worker_pool.release(lease).await.map_err(platform_error)?;
            }
            Ok::<(), BenchError>(())
        }));
    }
    barrier.wait().await;
    for worker in workers {
        worker.await.map_err(|error| {
            BenchError::new(format!("pool throughput worker failed to join: {error}"))
        })??;
    }
    let throughput_elapsed_micros = duration_micros(throughput_started.elapsed());
    let throughput_operations =
        u64::from(config.pool_capacity).saturating_mul(u64::from(config.pool_iterations));
    let throughput_operations_per_second = rate_per_second(
        throughput_operations,
        throughput_elapsed_micros,
    );
    let final_state = pool_snapshot(&pool.observations());

    Ok(PoolProbeReport {
        acquire_micros: distribution(&acquire_micros)
            .ok_or_else(|| BenchError::new("pool acquire probe produced no samples"))?,
        release_micros: distribution(&release_micros)
            .ok_or_else(|| BenchError::new("pool release probe produced no samples"))?,
        queued_wait_micros: distribution(&queued_wait_micros)
            .ok_or_else(|| BenchError::new("pool wait probe produced no samples"))?,
        overflow_rejected,
        overflow_error_code,
        throughput_operations,
        throughput_elapsed_micros,
        throughput_operations_per_second,
        maximum_observed_active_leases,
        maximum_observed_queue_depth,
        final_state,
    })
}

async fn wait_for_queue_depth(
    pool: &FixedCellPool,
    expected: u32,
) -> Result<(), BenchError> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = pool.observations();
        if snapshot.queue_depth == expected {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(BenchError::new(format!(
                "fixed pool did not reach queue depth {expected}; observed {}",
                snapshot.queue_depth
            )));
        }
        tokio::task::yield_now().await;
    }
}

async fn wait_for_activation_saturation(
    pool: &FixedCellPool,
    mode: ThroughputMode,
    expected_active: u32,
    expected_queue: u32,
) -> Result<(), BenchError> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = pool.observations();
        if snapshot.active_leases == expected_active && snapshot.queue_depth == expected_queue {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(BenchError::new(format!(
                "real {} activation workload did not reach its coordinated pool state: active={} expected={}, queue={} expected={}",
                mode.name(),
                snapshot.active_leases,
                expected_active,
                snapshot.queue_depth,
                expected_queue
            )));
        }
        tokio::task::yield_now().await;
    }
}

/// The two throughput conditions required by the Phase 0 baseline. Both hold
/// real acquired leases at the common gate until the raw pool proves the
/// condition, so a CPU-bound guest cannot serialize the observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ThroughputMode {
    AtCapacity,
    BoundedQueueSaturation,
}

impl ThroughputMode {
    const fn name(self) -> &'static str {
        match self {
            Self::AtCapacity => "at_capacity",
            Self::BoundedQueueSaturation => "bounded_queue_saturation",
        }
    }

    fn activations_per_batch(self, config: &EffectiveConfig) -> Result<u32, BenchError> {
        match self {
            Self::AtCapacity => Ok(config.pool_capacity),
            Self::BoundedQueueSaturation => config
                .pool_capacity
                .checked_add(config.pool_queue_capacity)
                .ok_or_else(|| BenchError::new("saturated activation count overflow")),
        }
    }

    const fn expected_queue_depth(self, config: &EffectiveConfig) -> u32 {
        match self {
            Self::AtCapacity => 0,
            Self::BoundedQueueSaturation => config.pool_queue_capacity,
        }
    }
}

async fn run_activation_throughput(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    timings: &PhaseTimingRecorder,
    saturation_gate: &ThroughputSaturationGate,
    workers: &RuntimeWorkerMonitor,
    process_entry: Instant,
    samples: &mut Vec<ActivationSample>,
) -> Result<ActivationThroughputReport, BenchError> {
    let at_capacity = run_throughput_mode(
        config,
        manifest,
        pool,
        backend,
        runner,
        timings,
        saturation_gate,
        workers,
        process_entry,
        ThroughputMode::AtCapacity,
        samples,
    )
    .await?;
    let bounded_queue_saturation = run_throughput_mode(
        config,
        manifest,
        pool,
        backend,
        runner,
        timings,
        saturation_gate,
        workers,
        process_entry,
        ThroughputMode::BoundedQueueSaturation,
        samples,
    )
    .await?;
    Ok(ActivationThroughputReport {
        at_capacity,
        bounded_queue_saturation,
    })
}

#[allow(clippy::too_many_arguments)]
async fn run_throughput_mode(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    timings: &PhaseTimingRecorder,
    saturation_gate: &ThroughputSaturationGate,
    workers: &RuntimeWorkerMonitor,
    process_entry: Instant,
    mode: ThroughputMode,
    samples: &mut Vec<ActivationSample>,
) -> Result<ThroughputModeReport, BenchError> {
    let mode_name = mode.name();
    let activations_per_batch = mode.activations_per_batch(config)?;
    let expected_queue_depth = mode.expected_queue_depth(config);
    let total_started = Instant::now();
    let mut batch_micros = Vec::new();
    let mut activation_latencies = Vec::new();
    let mut acquire_waits = Vec::new();
    let mut queued_acquire_waits = Vec::new();
    let mut activation_count = 0_u64;
    let mut maximum_observed_active_leases = 0_u32;
    let mut maximum_observed_queue_depth = 0_u32;

    for batch in 0..config.throughput_batches {
        // Both required modes acquire real leases before guest execution. This
        // proves the at-capacity state as well as the bounded-queue state.
        saturation_gate.close();
        let participant_count = usize::try_from(activations_per_batch)
            .map_err(|_| BenchError::new("activation batch size does not fit usize"))?;
        let barrier = Arc::new(Barrier::new(participant_count.saturating_add(1)));
        let done = Arc::new(AtomicBool::new(false));
        let monitor_pool = Arc::clone(pool);
        let monitor_done = Arc::clone(&done);
        let monitor = tokio::spawn(async move {
            let mut maximum_active = 0_u32;
            let mut maximum_queue = 0_u32;
            loop {
                let snapshot = monitor_pool.observations();
                maximum_active = maximum_active.max(snapshot.active_leases);
                maximum_queue = maximum_queue.max(snapshot.queue_depth);
                if monitor_done.load(Ordering::Acquire)
                    && snapshot.active_leases == 0
                    && snapshot.queue_depth == 0
                {
                    return (maximum_active, maximum_queue);
                }
                tokio::task::yield_now().await;
            }
        });

        let batch_started = Instant::now();
        let mut handles = Vec::new();
        for slot in 0..activations_per_batch {
            let activation_id = ActivationId(format!(
                "baseline-throughput-{mode_name}-{batch:08}-{slot:04}"
            ));
            let expected_output = format!("throughput-{mode_name}-{batch}-{slot}");
            let input = format!("{FIXTURE_DELAYED_ECHO_PREFIX}{expected_output}");
            let deadline = now_unix_millis().saturating_add(10_000);
            let envelope = phase0_composition::phase0_activation_envelope(
                manifest,
                &Phase0InvocationConfig {
                    activation_id: activation_id.clone(),
                    input: &input,
                    memory_bytes: config.memory_bytes,
                    fuel: config.fuel,
                    deadline_unix_millis: deadline,
                    surface: SURFACE,
                    mode: "phase0-baseline",
                    principal_subject: "phase0-baseline-user",
                    default_tenant: "phase0-baseline",
                    trace_id: TRACE_ID,
                    span_id: SPAN_ID,
                },
            );
            let worker_runner = Arc::clone(runner);
            let worker_barrier = Arc::clone(&barrier);
            let worker_timings = timings.clone();
            handles.push(tokio::spawn(async move {
                worker_barrier.wait().await;
                let started = Instant::now();
                let outcome = worker_runner.invoke(envelope).await;
                let elapsed_micros = duration_micros(started.elapsed());
                let phase_timings = worker_timings
                    .take_report(&activation_id, elapsed_micros)?;
                Ok::<_, BenchError>((
                    activation_id,
                    expected_output,
                    elapsed_micros,
                    phase_timings,
                    classify_outcome(outcome),
                ))
            }));
        }

        barrier.wait().await;
        let saturation_result = wait_for_activation_saturation(
            pool,
            mode,
            config.pool_capacity,
            expected_queue_depth,
        )
        .await;
        // Always release real leases, including when the proof fails, before
        // joining the participants so a failed assertion cannot deadlock the
        // benchmark process.
        saturation_gate.open();
        let mut completed = Vec::new();
        for handle in handles {
            completed.push(handle.await.map_err(|error| {
                BenchError::new(format!("activation throughput task failed: {error}"))
            })??);
        }
        done.store(true, Ordering::Release);
        let (batch_maximum_active, batch_maximum_queue) = monitor.await.map_err(|error| {
            BenchError::new(format!("activation throughput monitor failed: {error}"))
        })?;
        saturation_result?;
        maximum_observed_active_leases =
            maximum_observed_active_leases.max(batch_maximum_active);
        maximum_observed_queue_depth = maximum_observed_queue_depth.max(batch_maximum_queue);

        let elapsed = duration_micros(batch_started.elapsed());
        batch_micros.push(elapsed);
        activation_count = activation_count.saturating_add(u64::from(activations_per_batch));

        let pool_after = pool_snapshot(&pool.observations());
        let runner_after = runner_snapshot(&runner.snapshot());
        let prepared_cache_after = cache_snapshot(&backend.cache_snapshot());
        let backend_resources_after = runtime_resources(&backend.resource_snapshot());
        backend.log_sink().clear();
        let retained_log_entries_after_clear = backend.log_sink().snapshot().len();
        let observed_runtime_workers_after = workers.active_workers();
        let process_after = observe_process(
            &format!("after_throughput_{mode_name}_batch_{batch:08}"),
            process_entry,
        );

        for (activation_id, expected_output, elapsed_micros, phase_timings, outcome) in completed {
            activation_latencies.push(elapsed_micros);
            acquire_waits.push(phase_timings.acquire_or_queue_wait_micros);
            if phase_timings.acquisition_queued {
                queued_acquire_waits.push(phase_timings.acquire_or_queue_wait_micros);
            }
            let contract_result_valid = outcome.name == "success"
                && outcome.output_utf8.as_deref() == Some(expected_output.as_str());
            samples.push(ActivationSample {
                scenario: format!("throughput_{mode_name}"),
                iteration: u32::try_from(samples.len()).unwrap_or(u32::MAX),
                activation_id: activation_id.0,
                elapsed_micros,
                timeout_or_cancel_overshoot_micros: None,
                expected_outcome: "success".to_owned(),
                contract_result_valid,
                outcome,
                phase_timings,
                pool_after: pool_after.clone(),
                runner_after: runner_after.clone(),
                prepared_cache_after: prepared_cache_after.clone(),
                backend_resources_after: backend_resources_after.clone(),
                retained_log_entries_after_clear,
                observed_runtime_workers_after,
                process_after: process_after.clone(),
            });
        }
    }

    if maximum_observed_active_leases != config.pool_capacity
        || maximum_observed_queue_depth != expected_queue_depth
    {
        return Err(BenchError::new(format!(
            "real {} activation batch did not reach its coordinated pool state: active={} expected={}, queue={} expected={}",
            mode_name,
            maximum_observed_active_leases,
            config.pool_capacity,
            maximum_observed_queue_depth,
            expected_queue_depth
        )));
    }

    let elapsed_micros = duration_micros(total_started.elapsed());
    Ok(ThroughputModeReport {
        mode: mode_name.to_owned(),
        activations: activation_count,
        elapsed_micros,
        activations_per_second: rate_per_second(activation_count, elapsed_micros),
        batch_micros: distribution(&batch_micros)
            .ok_or_else(|| BenchError::new("activation throughput produced no batches"))?,
        activation_latency_micros: distribution(&activation_latencies)
            .ok_or_else(|| BenchError::new("activation throughput produced no samples"))?,
        acquire_wait_micros: distribution(&acquire_waits)
            .ok_or_else(|| BenchError::new("activation throughput produced no acquire samples"))?,
        queued_acquire_wait_micros: distribution(&queued_acquire_waits),
        maximum_observed_active_leases,
        maximum_observed_queue_depth,
    })
}

fn pool_budget(timeout_ms: u64) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1,
        memory_bytes: 1,
        wall_deadline_unix_millis: Some(now_unix_millis().saturating_add(timeout_ms)),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}
