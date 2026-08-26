async fn invoke_case(
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    timings: &PhaseTimingRecorder,
    workers: &RuntimeWorkerMonitor,
    process_entry: Instant,
    request: InvocationRequest<'_>,
) -> Result<ActivationSample, BenchError> {
    let activation_id = ActivationId(format!(
        "baseline-{}-{:08}",
        request.scenario.replace('_', "-"),
        request.iteration
    ));
    let deadline = now_unix_millis()
        .checked_add(request.timeout_ms)
        .ok_or_else(|| BenchError::new("activation deadline overflow"))?;
    let envelope = phase0_composition::phase0_activation_envelope(
        manifest,
        &Phase0InvocationConfig {
            activation_id: activation_id.clone(),
            input: request.input,
            memory_bytes: request.memory_bytes,
            fuel: request.fuel,
            deadline_unix_millis: deadline,
            surface: SURFACE,
            mode: "phase0-baseline",
            principal_subject: "phase0-baseline-user",
            default_tenant: "phase0-baseline",
            trace_id: TRACE_ID,
            span_id: SPAN_ID,
        },
    );

    let started = Instant::now();
    let invocation = runner.invoke(envelope);
    tokio::pin!(invocation);
    let outcome = if let Some(cancel_after_ms) = request.cancel_after_ms {
        tokio::select! {
            biased;
            outcome = &mut invocation => outcome,
            () = tokio::time::sleep(Duration::from_millis(cancel_after_ms)) => {
                let _ = runner
                    .cancel(&activation_id, "phase0 baseline explicit cancellation")
                    .await;
                invocation.await
            }
        }
    } else {
        invocation.await
    };
    let elapsed_micros = duration_micros(started.elapsed());
    let phase_timings = timings.take_report(&activation_id, elapsed_micros)?;
    let overshoot = match request.expected {
        ExpectedOutcome::Timeout => Some(
            elapsed_micros.saturating_sub(request.timeout_ms.saturating_mul(1_000)),
        ),
        ExpectedOutcome::Cancelled => Some(
            elapsed_micros.saturating_sub(
                request
                    .cancel_after_ms
                    .unwrap_or(0)
                    .saturating_mul(1_000),
            ),
        ),
        _ => None,
    };
    let outcome = classify_outcome(outcome);
    let contract_result_valid = outcome_matches(request.expected, request.input, &outcome);

    let runner_after = runner_snapshot(&runner.snapshot());
    let pool_after = pool_snapshot(&pool.observations());
    let prepared_cache_after = cache_snapshot(&backend.cache_snapshot());
    let backend_resources_after = runtime_resources(&backend.resource_snapshot());
    let log_sink = backend.log_sink();
    let _captured_logs = log_sink.snapshot_for(&activation_id);
    log_sink.clear();
    let retained_log_entries_after_clear = log_sink.snapshot().len();
    let observed_runtime_workers_after = workers.active_workers();
    let process_after = observe_process(
        &format!("after_{}_{:08}", request.scenario, request.iteration),
        process_entry,
    );

    Ok(ActivationSample {
        scenario: request.scenario.to_owned(),
        iteration: request.iteration,
        activation_id: activation_id.0,
        elapsed_micros,
        timeout_or_cancel_overshoot_micros: overshoot,
        expected_outcome: request.expected.name().to_owned(),
        contract_result_valid,
        outcome,
        phase_timings,
        pool_after,
        runner_after,
        prepared_cache_after,
        backend_resources_after,
        retained_log_entries_after_clear,
        observed_runtime_workers_after,
        process_after,
    })
}

fn classify_outcome(outcome: ActivationOutcome) -> OutcomeReport {
    match outcome {
        ActivationOutcome::Succeeded(success)
            if success.output_media_type == ECHO_DOMAIN_ERROR_MEDIA_TYPE =>
        {
            let error_code = serde_json::from_slice::<Value>(&success.output)
                .ok()
                .and_then(|document| {
                    document
                        .get("error")
                        .and_then(Value::as_str)
                        .map(str::to_owned)
                })
                .unwrap_or_else(|| "declared-domain-error".to_owned());
            OutcomeReport {
                name: "domain_error".to_owned(),
                error_code: Some(error_code),
                output_utf8: Some(String::from_utf8_lossy(&success.output).into_owned()),
                consumption: consumption_report(&success.consumption),
            }
        }
        ActivationOutcome::Succeeded(success) => OutcomeReport {
            name: "success".to_owned(),
            error_code: None,
            output_utf8: Some(String::from_utf8_lossy(&success.output).into_owned()),
            consumption: consumption_report(&success.consumption),
        },
        ActivationOutcome::Failed {
            error,
            consumption,
            ..
        } => {
            let name = match error.code {
                PlatformErrorCode::Cancelled => "cancelled",
                PlatformErrorCode::DeadlineExceeded => "timeout",
                PlatformErrorCode::GuestTrap => "trap",
                PlatformErrorCode::ResourceExhausted => "resource_exhausted",
                _ => "platform_failure",
            };
            OutcomeReport {
                name: name.to_owned(),
                error_code: Some(platform_error_code_name(error.code).to_owned()),
                output_utf8: None,
                consumption: consumption_report(&consumption),
            }
        }
    }
}

fn outcome_matches(expected: ExpectedOutcome, input: &str, outcome: &OutcomeReport) -> bool {
    if outcome.name != expected.name() {
        return false;
    }
    match expected {
        ExpectedOutcome::Success => outcome.output_utf8.as_deref() == Some(input),
        ExpectedOutcome::DomainError => outcome.error_code.as_deref() == Some("empty-message"),
        ExpectedOutcome::Trap => outcome.error_code.as_deref() == Some("guest_trap"),
        ExpectedOutcome::Timeout => outcome.error_code.as_deref() == Some("deadline_exceeded"),
        ExpectedOutcome::Cancelled => outcome.error_code.as_deref() == Some("cancelled"),
        ExpectedOutcome::ResourceExhausted => {
            outcome.error_code.as_deref() == Some("resource_exhausted")
        }
    }
}

fn consumption_report(consumption: &BudgetConsumption) -> ConsumptionReport {
    ConsumptionReport {
        cpu_fuel: consumption.cpu_fuel,
        peak_memory_bytes: consumption.peak_memory_bytes,
        wall_time_micros: consumption.wall_time_micros,
        log_bytes: consumption.log_bytes,
    }
}

fn platform_error_code_name(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "unavailable",
        PlatformErrorCode::DeadlineExceeded => "deadline_exceeded",
        PlatformErrorCode::Cancelled => "cancelled",
        PlatformErrorCode::ResourceExhausted => "resource_exhausted",
        PlatformErrorCode::PermissionDenied => "permission_denied",
        PlatformErrorCode::Unauthenticated => "unauthenticated",
        PlatformErrorCode::InvalidArgument => "invalid_argument",
        PlatformErrorCode::NotFound => "not_found",
        PlatformErrorCode::AlreadyExists => "already_exists",
        PlatformErrorCode::IncompatibleContract => "incompatible_contract",
        PlatformErrorCode::StateConflict => "state_conflict",
        PlatformErrorCode::DependencyFailed => "dependency_failed",
        PlatformErrorCode::GuestTrap => "guest_trap",
        PlatformErrorCode::CorruptArtifact => "corrupt_artifact",
        PlatformErrorCode::RouteUnavailable => "route_unavailable",
        PlatformErrorCode::AdmissionRejected => "admission_rejected",
        PlatformErrorCode::Internal => "internal",
        _ => "unknown",
    }
}
