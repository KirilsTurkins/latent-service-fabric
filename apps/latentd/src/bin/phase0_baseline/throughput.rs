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
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
}

async fn run_activation_throughput(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    process_entry: Instant,
    samples: &mut Vec<ActivationSample>,
) -> Result<ActivationThroughputReport, BenchError> {
    let total_started = Instant::now();
    let mut batch_micros = Vec::new();
    let mut activation_count = 0_u64;

    for batch in 0..config.throughput_batches {
        let batch_started = Instant::now();
        let mut handles = Vec::new();
        for slot in 0..config.pool_capacity {
            let activation_id = ActivationId(format!(
                "baseline-throughput-{batch:08}-{slot:04}"
            ));
            let expected_output = format!("throughput-{batch}-{slot}");
            let input = format!("{FIXTURE_DELAYED_ECHO_PREFIX}{expected_output}");
            let deadline = now_unix_millis().saturating_add(5_000);
            let envelope = activation_envelope(
                manifest,
                activation_id.clone(),
                &input,
                config.memory_bytes,
                config.fuel,
                deadline,
            );
            let worker_runner = Arc::clone(runner);
            handles.push(tokio::spawn(async move {
                let started = Instant::now();
                let outcome = worker_runner.invoke(envelope).await;
                (
                    activation_id,
                    expected_output,
                    duration_micros(started.elapsed()),
                    classify_outcome(outcome),
                )
            }));
        }

        let mut completed = Vec::new();
        for handle in handles {
            completed.push(handle.await.map_err(|error| {
                BenchError::new(format!("activation throughput task failed: {error}"))
            })?);
        }
        let elapsed = duration_micros(batch_started.elapsed());
        batch_micros.push(elapsed);
        activation_count = activation_count.saturating_add(u64::from(config.pool_capacity));

        let pool_after = pool_snapshot(&pool.observations());
        let runner_after = runner_snapshot(&runner.snapshot());
        let prepared_cache_after = cache_snapshot(&backend.cache_snapshot());
        let backend_resources_after = runtime_resources(&backend.resource_snapshot());
        backend.log_sink().clear();
        let retained_log_entries_after_clear = backend.log_sink().snapshot().len();
        let process_after = observe_process(
            &format!("after_throughput_batch_{batch:08}"),
            process_entry,
        );

        for (activation_id, expected_output, activation_elapsed, outcome) in completed {
            let contract_result_valid = outcome.name == "success"
                && outcome.output_utf8.as_deref() == Some(expected_output.as_str());
            samples.push(ActivationSample {
                scenario: "throughput_echo".to_owned(),
                iteration: u32::try_from(samples.len()).unwrap_or(u32::MAX),
                activation_id: activation_id.0,
                elapsed_micros: activation_elapsed,
                timeout_or_cancel_overshoot_micros: None,
                expected_outcome: "success".to_owned(),
                contract_result_valid,
                outcome,
                pool_after: pool_after.clone(),
                runner_after: runner_after.clone(),
                prepared_cache_after: prepared_cache_after.clone(),
                backend_resources_after: backend_resources_after.clone(),
                retained_log_entries_after_clear,
                process_after: process_after.clone(),
            });
        }
    }

    let elapsed_micros = duration_micros(total_started.elapsed());
    Ok(ActivationThroughputReport {
        activations: activation_count,
        elapsed_micros,
        activations_per_second: rate_per_second(activation_count, elapsed_micros),
        batch_micros: distribution(&batch_micros)
            .ok_or_else(|| BenchError::new("activation throughput produced no batches"))?,
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
