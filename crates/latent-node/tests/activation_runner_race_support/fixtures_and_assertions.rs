fn make_runner<P>(pool: Arc<P>, backend: Arc<Backend>) -> Arc<Phase0ActivationRunner>
where
    P: CellPool + 'static,
{
    let pool: Arc<dyn CellPool> = pool;
    let backend: Arc<dyn ExecutionBackend> = backend;
    Arc::new(
        Phase0ActivationRunner::new(
            Phase0ActivationRunnerConfig::default(),
            pool,
            backend,
            prepared(),
            vec![BoundImport {
                capability: CapabilityId("race-capability".to_owned()),
                contract: "test:race/api@0.1.0".to_owned(),
                opaque_handle: "race-handle".to_owned(),
            }],
        )
        .expect("race runner is valid"),
    )
}

fn prepared() -> PreparedComponent {
    PreparedComponent {
        key: PreparationKey {
            release: ReleaseDigest("sha256:runner-race".to_owned()),
            engine_version: "race-engine".to_owned(),
            engine_configuration_digest: "sha256:race-config".to_owned(),
            target_triple: "race-target".to_owned(),
            cpu_feature_set: "race-features".to_owned(),
        },
        backend: BACKEND_ID.to_owned(),
        opaque_handle: "race-prepared".to_owned(),
        metadata: Metadata::new(),
    }
}

fn envelope(id: ActivationId, deadline: Option<u64>) -> ActivationEnvelope {
    let tenant = TenantId("race-tenant".to_owned());
    ActivationEnvelope {
        activation_id: id.clone(),
        parent_activation_id: None,
        root_activation_id: id,
        principal: InvocationPrincipal {
            subject: "service:race".to_owned(),
            kind: PrincipalKind::Service,
            tenant: Some(tenant.clone()),
            service: Some(ServiceId("race-service".to_owned())),
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant,
            service: ServiceId("race-service".to_owned()),
            contract: ContractId("test:race/api@0.1.0".to_owned()),
            function: FunctionId("run".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: deadline,
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId("race-trace".to_owned()),
            span_id: SpanId("race-span".to_owned()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 16 * 1024 * 1024,
            wall_time_limit_millis: None,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 4096,
            effect_count: 0,
        },
        metadata: Metadata::new(),
        input: b"race".to_vec(),
        input_media_type: "text/plain".to_owned(),
    }
}

fn lease(
    id: ActivationId,
    class: CellClass,
    budget: ResourceBudget,
    lifecycle: Arc<Lifecycle>,
) -> CellLease {
    let lifecycle: Arc<dyn CellLeaseLifecycle> = lifecycle;
    CellLease::new(
        CellId(format!("race-cell-{}", id.0)),
        id,
        NodeId("race-node".to_owned()),
        class,
        budget,
        now().saturating_add(60_000),
        lifecycle,
    )
}

fn success_report(used: BudgetConsumption) -> ExecutionReport {
    ExecutionReport::reusable(Ok(returned(b"completed", used)))
}

fn returned(output: &[u8], used: BudgetConsumption) -> GuestOutcome {
    GuestOutcome::Returned {
        output: output.to_vec(),
        output_media_type: "text/plain".to_owned(),
        consumption: used,
    }
}

fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 41,
        peak_memory_bytes: 8192,
        wall_time_micros: 73,
        log_bytes: 17,
        ..BudgetConsumption::default()
    }
}

fn spawn(
    runner: Arc<Phase0ActivationRunner>,
    envelope: ActivationEnvelope,
) -> tokio::task::JoinHandle<ActivationOutcome> {
    tokio::spawn(async move { runner.invoke(envelope).await })
}

async fn join(
    task: tokio::task::JoinHandle<ActivationOutcome>,
    label: &str,
) -> ActivationOutcome {
    tokio::time::timeout(TEST_TIMEOUT, task)
        .await
        .unwrap_or_else(|_| panic!("{label} timed out"))
        .unwrap_or_else(|error| panic!("{label} task failed: {error}"))
}

async fn rendezvous(barrier: &Barrier, label: &str) {
    tokio::time::timeout(TEST_TIMEOUT, barrier.wait())
        .await
        .unwrap_or_else(|_| panic!("{label} timed out"));
}

fn spin_past(deadline: u64) {
    let started = Instant::now();
    while now() <= deadline {
        assert!(started.elapsed() < TEST_TIMEOUT, "deadline did not elapse");
        std::hint::spin_loop();
    }
}

async fn wait_past(deadline: u64) {
    tokio::time::timeout(TEST_TIMEOUT, async move {
        while now() <= deadline {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("deadline becomes visible while backend is blocked");
}

fn assert_success(outcome: ActivationOutcome, expected: &BudgetConsumption) {
    match outcome {
        ActivationOutcome::Succeeded(success) => {
            assert_eq!(success.output, b"completed");
            assert_eq!(&success.consumption, expected);
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            panic!("unexpected declared error: {error:?}");
        }
        ActivationOutcome::Failed { error, .. } => panic!("unexpected failure: {error:?}"),
    }
}

fn assert_failure(
    outcome: ActivationOutcome,
    terminal: ActivationTerminalState,
    code: PlatformErrorCode,
    detail: &str,
    expected: &BudgetConsumption,
) {
    match outcome {
        ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption,
        } => {
            assert_eq!(terminal_state, terminal);
            assert_eq!(error.code, code);
            assert_eq!(
                error.details.first().map(|item| item.kind.as_str()),
                Some(detail)
            );
            assert_eq!(&consumption, expected);
        }
        ActivationOutcome::Succeeded(success) => {
            panic!("expected failure, got {:?}", success.output);
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            panic!("expected platform failure, got declared error: {error:?}");
        }
    }
}

fn assert_disposition_failure(runner: &Phase0ActivationRunner, pool: &Pool) {
    let snapshot = runner.snapshot();
    assert_eq!(snapshot.disposition_failures, 1);
    assert_eq!(snapshot.released_cells, 0);
    assert_eq!(snapshot.quarantined_cells, 0);
    assert_eq!(snapshot.active_cancellation_registrations, 0);
    assert_eq!(pool.abandoned(), 1);
}

fn test_error(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn now() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}
