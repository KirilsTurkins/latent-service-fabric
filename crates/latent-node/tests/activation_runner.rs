use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, ActivationTerminalState, BoxFuture, BudgetConsumption, CapabilityId, ContractId,
    ErrorDetail, FunctionId, InvocationPrincipal, Metadata, NodeId, PlatformError,
    PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest,
    GuestInterruptionKind, GuestOutcome, GuestTrap, PreparationKey, PreparedComponent,
};
use latent_node::{Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_routing::InvocationTarget;
use latent_scheduler::{CellClass, FixedCellPool, FixedCellPoolConfig};

const BACKEND_ID: &str = "scripted-containment-test";

#[derive(Default)]
struct ScriptedBackend {
    hold_released: AtomicBool,
    hold_started: AtomicU64,
}

impl ScriptedBackend {
    fn release_holds(&self) {
        self.hold_released.store(true, Ordering::Release);
    }

    fn hold_started(&self) -> u64 {
        self.hold_started.load(Ordering::Acquire)
    }

    async fn execute(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
    ) -> ExecutionReport {
        let mode = String::from_utf8_lossy(&request.activation.input).into_owned();
        let consumption = BudgetConsumption {
            cpu_fuel: 7,
            peak_memory_bytes: 4096,
            wall_time_micros: 11,
            ..BudgetConsumption::default()
        };

        if let Some(output) = mode.strip_prefix("echo:") {
            return ExecutionReport::reusable(Ok(returned(output.as_bytes(), consumption)));
        }
        if let Some(output) = mode.strip_prefix("healthy-slow:") {
            tokio::time::sleep(Duration::from_millis(5)).await;
            return ExecutionReport::reusable(Ok(returned(output.as_bytes(), consumption)));
        }

        match mode.as_str() {
            "trap" => {
                let mut metadata = Metadata::new();
                metadata.insert("guest-value".to_owned(), "sensitive".repeat(128));
                ExecutionReport::reusable(Ok(GuestOutcome::Trapped {
                    trap: GuestTrap {
                        code: "controlled-trap".to_owned(),
                        message: "guest trap detail ".repeat(128),
                        guest_backtrace: vec!["guest-frame".repeat(128)],
                        metadata,
                    },
                    consumption,
                }))
            }
            "deadline" => ExecutionReport::reusable(Ok(GuestOutcome::Interrupted {
                kind: GuestInterruptionKind::DeadlineExceeded,
                reason: "deadline diagnostic ".repeat(128),
                consumption,
            })),
            "fuel" => ExecutionReport::reusable(Ok(GuestOutcome::Interrupted {
                kind: GuestInterruptionKind::FuelExhausted,
                reason: "fuel diagnostic ".repeat(128),
                consumption,
            })),
            "memory" => ExecutionReport::reusable(Ok(GuestOutcome::Interrupted {
                kind: GuestInterruptionKind::MemoryExhausted,
                reason: "memory diagnostic ".repeat(128),
                consumption,
            })),
            "engine" => {
                let mut fields = BTreeMap::new();
                for index in 0..32 {
                    fields.insert(
                        format!("field-{index}-{}", "n".repeat(128)),
                        "v".repeat(1024),
                    );
                }
                ExecutionReport::reusable(Err(PlatformError {
                    code: PlatformErrorCode::Internal,
                    message: "engine diagnostic ".repeat(256),
                    retryable: false,
                    details: vec![
                        ErrorDetail {
                            kind: "engine-detail".repeat(64),
                            fields,
                        };
                        16
                    ],
                }))
            }
            "wait-cancel" => {
                while !cancellation.is_cancelled() {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
                ExecutionReport::reusable(Ok(GuestOutcome::Interrupted {
                    kind: GuestInterruptionKind::Cancelled,
                    reason: cancellation
                        .reason()
                        .unwrap_or_else(|| "activation cancelled".to_owned()),
                    consumption,
                }))
            }
            "hold" => {
                self.hold_started.fetch_add(1, Ordering::AcqRel);
                while !self.hold_released.load(Ordering::Acquire) {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
                ExecutionReport::reusable(Ok(returned(b"hold-complete", consumption)))
            }
            "quarantine" => ExecutionReport::quarantine(
                Ok(returned(b"completed-before-quarantine", consumption)),
                "unsafe cleanup proof ".repeat(128),
            ),
            other => ExecutionReport::reusable(Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: format!("unknown scripted mode: {other}"),
                retryable: false,
                details: Vec::new(),
            })),
        }
    }
}

impl ExecutionBackend for ScriptedBackend {
    fn backend_id(&self) -> &str {
        BACKEND_ID
    }

    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move {
            Err(PlatformError {
                code: PlatformErrorCode::Internal,
                message: "scripted backend does not prepare artifacts".to_owned(),
                retryable: false,
                details: Vec::new(),
            })
        })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move { self.execute(request, cancellation).await.outcome })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move { self.execute(request, cancellation).await })
    }

    fn release<'a>(
        &'a self,
        _prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { Ok(()) })
    }
}

struct LegacyBackend;

impl ExecutionBackend for LegacyBackend {
    fn backend_id(&self) -> &str {
        "legacy-containment-test"
    }

    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move {
            Err(PlatformError {
                code: PlatformErrorCode::Internal,
                message: "legacy backend does not prepare artifacts".to_owned(),
                retryable: false,
                details: Vec::new(),
            })
        })
    }

    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move { Ok(returned(b"legacy-success", BudgetConsumption::default())) })
    }

    fn release<'a>(
        &'a self,
        _prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { Ok(()) })
    }
}

#[tokio::test]
async fn maps_every_terminal_failure_and_keeps_the_process_healthy() {
    let (runner, pool, _) = scripted_runner(1);
    let cases = [
        (
            "trap",
            ActivationTerminalState::GuestTrap,
            PlatformErrorCode::GuestTrap,
            "activation.guest-trap",
        ),
        (
            "deadline",
            ActivationTerminalState::DeadlineExceeded,
            PlatformErrorCode::DeadlineExceeded,
            "activation.deadline-exceeded",
        ),
        (
            "fuel",
            ActivationTerminalState::ResourceExhausted,
            PlatformErrorCode::ResourceExhausted,
            "activation.fuel-exhausted",
        ),
        (
            "memory",
            ActivationTerminalState::ResourceExhausted,
            PlatformErrorCode::ResourceExhausted,
            "activation.memory-exhausted",
        ),
        (
            "engine",
            ActivationTerminalState::PlatformFailed,
            PlatformErrorCode::Internal,
            "engine-detailengine-detailengine-detailengine-detailengine-detai",
        ),
    ];

    for (index, (mode, terminal_state, code, detail_prefix)) in cases.into_iter().enumerate() {
        let outcome = invoke_with_timeout(&runner, envelope(index as u64, mode)).await;
        let error = assert_failure(outcome, terminal_state, code);
        assert!(error.message.len() <= 512);
        assert!(error.details.len() <= 8);
        assert!(error
            .details
            .first()
            .is_some_and(|detail| detail.kind.starts_with(detail_prefix)));
        assert!(error.details.iter().all(|detail| {
            detail.kind.len() <= 64
                && detail.fields.len() <= 16
                && detail
                    .fields
                    .iter()
                    .all(|(name, value)| name.len() <= 64 && value.len() <= 256)
        }));

        let echo = format!("echo:healthy-{index}");
        assert_success(
            invoke_with_timeout(&runner, envelope(100 + index as u64, &echo)).await,
            format!("healthy-{index}").as_bytes(),
        );
        assert_reclaimed(&runner, &pool, 1);
    }
}

#[tokio::test]
async fn cancellation_interrupts_queued_and_running_activations() {
    let (runner, pool, backend) = scripted_runner(1);

    let holder_id = ActivationId("activation-holder".to_owned());
    let holder = {
        let runner = Arc::clone(&runner);
        let envelope = envelope_with_id(holder_id.clone(), "hold");
        tokio::spawn(async move { runner.invoke(envelope).await })
    };
    wait_until(|| backend.hold_started() == 1).await;

    let queued_id = ActivationId("activation-queued".to_owned());
    let queued = {
        let runner = Arc::clone(&runner);
        let envelope = envelope_with_id(queued_id.clone(), "echo:must-not-run");
        tokio::spawn(async move { runner.invoke(envelope).await })
    };
    wait_until(|| pool.observations().queue_depth == 1).await;
    runner
        .cancel(&queued_id, &"queue-cancel-reason".repeat(64))
        .await
        .expect("queued cancellation is accepted");
    let queued_outcome = tokio::time::timeout(Duration::from_secs(2), queued)
        .await
        .expect("queued cancellation completes")
        .expect("queued task joins");
    let queued_error = assert_failure(
        queued_outcome,
        ActivationTerminalState::Cancelled,
        PlatformErrorCode::Cancelled,
    );
    assert!(queued_error.message.len() <= 256);

    backend.release_holds();
    assert_success(
        tokio::time::timeout(Duration::from_secs(2), holder)
            .await
            .expect("holder completes")
            .expect("holder joins"),
        b"hold-complete",
    );
    assert_reclaimed(&runner, &pool, 1);

    let running_id = ActivationId("activation-running".to_owned());
    let running = {
        let runner = Arc::clone(&runner);
        let envelope = envelope_with_id(running_id.clone(), "wait-cancel");
        tokio::spawn(async move { runner.invoke(envelope).await })
    };
    wait_until(|| runner.snapshot().running_invocations == 1).await;
    runner
        .cancel(&running_id, "running-cancel")
        .await
        .expect("running cancellation is accepted");
    let running_outcome = tokio::time::timeout(Duration::from_secs(2), running)
        .await
        .expect("running cancellation completes")
        .expect("running task joins");
    assert_failure(
        running_outcome,
        ActivationTerminalState::Cancelled,
        PlatformErrorCode::Cancelled,
    );
    assert_reclaimed(&runner, &pool, 1);
}

#[tokio::test]
async fn cleanup_proof_controls_exactly_once_cell_disposition() {
    let (runner, pool, _) = scripted_runner(2);
    assert_success(
        invoke_with_timeout(&runner, envelope(1, "quarantine")).await,
        b"completed-before-quarantine",
    );

    let observations = pool.observations();
    assert_eq!(observations.capacity, 2);
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
    let snapshot = runner.snapshot();
    assert_eq!(snapshot.quarantined_cells, 1);
    assert_eq!(snapshot.released_cells, 0);
    assert_eq!(snapshot.disposition_failures, 0);
    assert_eq!(snapshot.active_cancellation_registrations, 0);

    let (legacy_runner, legacy_pool) = legacy_runner();
    assert_success(
        invoke_with_timeout(&legacy_runner, envelope(2, "ignored")).await,
        b"legacy-success",
    );
    let observations = legacy_pool.observations();
    assert_eq!(observations.available, 0);
    assert_eq!(observations.quarantined, 1);
    assert_eq!(legacy_runner.snapshot().quarantined_cells, 1);
}

#[tokio::test]
async fn repeated_failures_leave_no_runner_or_pool_resources_live() {
    let (runner, pool, _) = scripted_runner(2);
    let modes = ["trap", "deadline", "fuel", "memory", "engine"];

    for index in 0..128_u64 {
        let mode = modes[usize::try_from(index % modes.len() as u64).expect("index fits")];
        let outcome = invoke_with_timeout(&runner, envelope(1_000 + index, mode)).await;
        assert!(matches!(outcome, ActivationOutcome::Failed { .. }));
        assert_reclaimed(&runner, &pool, 2);
    }

    assert_success(
        invoke_with_timeout(&runner, envelope(2_000, "echo:post-failure")).await,
        b"post-failure",
    );
    assert_reclaimed(&runner, &pool, 2);
}

#[tokio::test]
async fn concurrent_healthy_activations_return_their_own_outputs() {
    let (runner, pool, _) = scripted_runner(4);
    let mut tasks = Vec::new();
    for index in 0..32_u64 {
        let runner = Arc::clone(&runner);
        let mode = format!("healthy-slow:output-{index}");
        tasks.push(tokio::spawn(async move {
            (index, runner.invoke(envelope(10_000 + index, &mode)).await)
        }));
    }

    for task in tasks {
        let (index, outcome) = tokio::time::timeout(Duration::from_secs(2), task)
            .await
            .expect("healthy invocation completes")
            .expect("healthy task joins");
        assert_success(outcome, format!("output-{index}").as_bytes());
    }
    assert_reclaimed(&runner, &pool, 4);
}

fn scripted_runner(
    capacity: u32,
) -> (
    Arc<Phase0ActivationRunner>,
    FixedCellPool,
    Arc<ScriptedBackend>,
) {
    let backend = Arc::new(ScriptedBackend::default());
    let runner_backend: Arc<dyn ExecutionBackend> = backend.clone();
    let pool = FixedCellPool::new(FixedCellPoolConfig::new(
        NodeId("node-test".to_owned()),
        CellClass::Standard,
        capacity,
        64,
    ))
    .expect("test pool is valid");
    let runner_pool: Arc<dyn latent_scheduler::CellPool> = Arc::new(pool.clone());
    let runner = Arc::new(
        Phase0ActivationRunner::new(
            Phase0ActivationRunnerConfig::default(),
            runner_pool,
            runner_backend,
            prepared(BACKEND_ID),
            vec![BoundImport {
                capability: CapabilityId("test-capability".to_owned()),
                contract: "test:capability/api@0.1.0".to_owned(),
                opaque_handle: "test-handle".to_owned(),
            }],
        )
        .expect("test runner is valid"),
    );
    (runner, pool, backend)
}

fn legacy_runner() -> (Arc<Phase0ActivationRunner>, FixedCellPool) {
    let pool = FixedCellPool::new(FixedCellPoolConfig::new(
        NodeId("legacy-node".to_owned()),
        CellClass::Standard,
        1,
        1,
    ))
    .expect("legacy test pool is valid");
    let runner_pool: Arc<dyn latent_scheduler::CellPool> = Arc::new(pool.clone());
    let backend: Arc<dyn ExecutionBackend> = Arc::new(LegacyBackend);
    let runner = Arc::new(
        Phase0ActivationRunner::new(
            Phase0ActivationRunnerConfig::default(),
            runner_pool,
            backend,
            prepared("legacy-containment-test"),
            Vec::new(),
        )
        .expect("legacy runner is valid"),
    );
    (runner, pool)
}

fn prepared(backend: &str) -> PreparedComponent {
    PreparedComponent {
        key: PreparationKey {
            release: ReleaseDigest("sha256:test".to_owned()),
            engine_version: "test".to_owned(),
            engine_configuration_digest: "sha256:test-config".to_owned(),
            target_triple: "test-target".to_owned(),
            cpu_feature_set: "test-features".to_owned(),
        },
        backend: backend.to_owned(),
        opaque_handle: "prepared-test-component".to_owned(),
        metadata: Metadata::new(),
    }
}

fn envelope(index: u64, input: &str) -> ActivationEnvelope {
    envelope_with_id(ActivationId(format!("activation-{index}")), input)
}

fn envelope_with_id(activation_id: ActivationId, input: &str) -> ActivationEnvelope {
    let tenant = TenantId("tenant-test".to_owned());
    let deadline = now_unix_millis().saturating_add(10_000);
    ActivationEnvelope {
        activation_id: activation_id.clone(),
        parent_activation_id: None,
        root_activation_id: activation_id,
        principal: InvocationPrincipal {
            subject: "service:test".to_owned(),
            kind: PrincipalKind::Service,
            tenant: Some(tenant.clone()),
            service: Some(ServiceId("service-test".to_owned())),
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant,
            service: ServiceId("service-test".to_owned()),
            contract: ContractId("test:service/api@0.1.0".to_owned()),
            function: FunctionId("run".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: Some(deadline),
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId("trace-test".to_owned()),
            span_id: SpanId("span-test".to_owned()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 16 * 1024 * 1024,
            wall_deadline_unix_millis: Some(deadline),
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
        input: input.as_bytes().to_vec(),
        input_media_type: "text/plain".to_owned(),
    }
}

fn returned(output: &[u8], consumption: BudgetConsumption) -> GuestOutcome {
    GuestOutcome::Returned {
        output: output.to_vec(),
        output_media_type: "text/plain".to_owned(),
        consumption,
    }
}

async fn invoke_with_timeout(
    runner: &Phase0ActivationRunner,
    envelope: ActivationEnvelope,
) -> ActivationOutcome {
    tokio::time::timeout(Duration::from_secs(2), runner.invoke(envelope))
        .await
        .expect("activation completes")
}

fn assert_success(outcome: ActivationOutcome, expected_output: &[u8]) {
    match outcome {
        ActivationOutcome::Succeeded(success) => {
            assert_eq!(success.output, expected_output);
        }
        ActivationOutcome::Failed { error, .. } => {
            panic!("expected success, got {:?}: {}", error.code, error.message);
        }
    }
}

fn assert_failure(
    outcome: ActivationOutcome,
    expected_terminal_state: ActivationTerminalState,
    expected_code: PlatformErrorCode,
) -> PlatformError {
    match outcome {
        ActivationOutcome::Failed {
            terminal_state,
            error,
            ..
        } => {
            assert_eq!(terminal_state, expected_terminal_state);
            assert_eq!(error.code, expected_code);
            error
        }
        ActivationOutcome::Succeeded(success) => {
            panic!("expected failure, got output {:?}", success.output);
        }
    }
}

fn assert_reclaimed(
    runner: &Phase0ActivationRunner,
    pool: &FixedCellPool,
    expected_available: u32,
) {
    let snapshot = runner.snapshot();
    assert_eq!(snapshot.active_cancellation_registrations, 0);
    assert_eq!(snapshot.running_invocations, 0);
    assert_eq!(snapshot.disposition_failures, 0);

    let observations = pool.observations();
    assert_eq!(observations.available, expected_available);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.queue_depth, 0);
}

async fn wait_until(predicate: impl Fn() -> bool) {
    tokio::time::timeout(Duration::from_secs(2), async move {
        while !predicate() {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("condition becomes true");
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}
