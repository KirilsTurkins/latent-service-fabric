//! Contract integration with the existing runner and real affine cell pool.
//! The backend injects explicit guest outcomes; it is not a Wasmtime test.

use std::sync::atomic::AtomicUsize;
use std::task::Poll;

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    BoxFuture, BudgetConsumption, DeclaredError, NodeId, PlatformError, SpanId, TraceId,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest,
    GuestInterruptionKind, GuestOutcome, GuestTrap, PreparationKey, PreparedComponent,
};
use latent_node::{Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_scheduler::{CellClass, CellPool, FixedCellPool, FixedCellPoolConfig};
use tokio::sync::Notify;

use super::*;

#[derive(Clone, Copy, Debug)]
enum Mode {
    Success,
    Declared,
    Trap,
    Deadline,
    Fuel,
    PlatformFailure,
    CleanupFailure,
    Blocked,
}

struct FaultBackend {
    mode: Mode,
    calls: AtomicUsize,
    resume: Notify,
}

fn injected_error(code: Code) -> PlatformError {
    PlatformError {
        code,
        message: "injected downstream failure".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

impl ExecutionBackend for FaultBackend {
    fn backend_id(&self) -> &str {
        "admission-test"
    }

    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move { Ok(prepared(key.clone())) })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if matches!(self.mode, Mode::Blocked) {
                self.resume.notified().await;
            }
            let consumption = BudgetConsumption {
                cpu_fuel: 1,
                peak_memory_bytes: 65_536,
                ..BudgetConsumption::default()
            };
            if cancellation.is_cancelled() {
                return Ok(GuestOutcome::Interrupted {
                    kind: GuestInterruptionKind::Cancelled,
                    reason: "test cancellation observed".to_owned(),
                    consumption,
                });
            }
            match self.mode {
                Mode::Declared => Ok(GuestOutcome::DeclaredError {
                    error: DeclaredError {
                        code: "expected-domain-error".to_owned(),
                        message: "declared failure".to_owned(),
                        payload: Vec::new(),
                        media_type: "application/octet-stream".to_owned(),
                        metadata: Metadata::new(),
                    },
                    consumption,
                }),
                Mode::Trap => Ok(GuestOutcome::Trapped {
                    trap: GuestTrap {
                        code: "unreachable".to_owned(),
                        message: "test trap".to_owned(),
                        guest_backtrace: Vec::new(),
                        metadata: Metadata::new(),
                    },
                    consumption,
                }),
                Mode::Deadline | Mode::Fuel => Ok(GuestOutcome::Interrupted {
                    kind: if matches!(self.mode, Mode::Deadline) {
                        GuestInterruptionKind::DeadlineExceeded
                    } else {
                        GuestInterruptionKind::FuelExhausted
                    },
                    reason: "test budget interruption".to_owned(),
                    consumption,
                }),
                Mode::PlatformFailure => Err(injected_error(Code::Unavailable)),
                Mode::Success | Mode::CleanupFailure | Mode::Blocked => {
                    Ok(GuestOutcome::Returned {
                        output: request.activation.input,
                        output_media_type: "application/octet-stream".to_owned(),
                        consumption,
                    })
                }
            }
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let outcome = self.invoke(request, cancellation).await;
            if matches!(self.mode, Mode::CleanupFailure) {
                ExecutionReport::quarantine(outcome, "injected uncertain reset")
            } else {
                ExecutionReport::reusable(outcome)
            }
        })
    }

    fn release(&self, _prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async { Ok(()) })
    }
}

fn prepared(key: PreparationKey) -> PreparedComponent {
    PreparedComponent {
        key,
        backend: "admission-test".to_owned(),
        opaque_handle: "test-component".to_owned(),
        metadata: Metadata::new(),
    }
}

struct Fixture {
    admission: LocalAdmissionController,
    quotas: LocalQuotaProvider,
    revision: ResolvedRevision,
    pool: Arc<FixedCellPool>,
    runner: Phase0ActivationRunner,
    backend: Arc<FaultBackend>,
}

impl Fixture {
    fn new(mode: Mode, queue_capacity: u32) -> Self {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let digest = releases.add("runner-admission");
        let store = open(&root, &releases);
        run(store.apply(deployment("blue", "alice", &digest))).unwrap();
        let (admission, quotas, _) = controller(&store, 3);
        let revision = store.resolve(&target("alice", None), None).unwrap();
        let pool = Arc::new(
            FixedCellPool::new(FixedCellPoolConfig::new(
                NodeId("admission-test-node".to_owned()),
                CellClass::Tiny,
                1,
                queue_capacity,
            ))
            .unwrap(),
        );
        let backend = Arc::new(FaultBackend {
            mode,
            calls: AtomicUsize::new(0),
            resume: Notify::new(),
        });
        let runner = Phase0ActivationRunner::new(
            Phase0ActivationRunnerConfig {
                cell_class: CellClass::Tiny,
                ..Phase0ActivationRunnerConfig::default()
            },
            pool.clone(),
            backend.clone(),
            prepared(PreparationKey {
                release: digest,
                engine_version: "test".to_owned(),
                engine_configuration_digest: "test".to_owned(),
                target_triple: "test".to_owned(),
                cpu_feature_set: "test".to_owned(),
            }),
            Vec::new(),
        )
        .unwrap();
        // The controller owns its immutable catalog pin. Neither lookup nor
        // admission needs the repository, directory, or artifact source afterward.
        drop(store);
        drop(root);
        Self {
            admission,
            quotas,
            revision,
            pool,
            runner,
            backend,
        }
    }

    fn request(&self, id: &str) -> AdmissionRequest {
        request(id, self.revision.clone(), &self.quotas)
    }

    async fn invoke(&self, request: AdmissionRequest) -> Result<ActivationOutcome, PlatformError> {
        let principal = request.principal.clone();
        let permit = self.admission.admit_now(request)?;
        let id = permit.activation_id().clone();
        let accounting = ActivationBudget::new(permit.effective_budget().clone());
        let envelope = ActivationEnvelope {
            activation_id: id.clone(),
            parent_activation_id: None,
            root_activation_id: id,
            principal,
            target: permit.revision().target.clone(),
            resolved_revision: Some(permit.revision().clone()),
            deadline_unix_millis: permit.deadline().unix_millis(),
            priority: permit.obligations().priority,
            trace: TraceContext {
                trace_id: TraceId("admission-test-trace".to_owned()),
                span_id: SpanId("admission-test-span".to_owned()),
                trace_flags: 0,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: permit.granted_budget().clone(),
            metadata: Metadata::new(),
            input: b"test".to_vec(),
            input_media_type: "application/octet-stream".to_owned(),
        };
        // The legacy runner has no admission handoff hook. This test bridge
        // conservatively retains the queued permit through cell disposition.
        // The queued -> execution permit transition has separate unit tests;
        // production orchestration and prompt queue-slot return belong to #11.
        let outcome = self.runner.invoke(envelope).await;
        assert_eq!(self.quotas.usage().unwrap().active_activations, 1);
        assert_eq!(self.runner.snapshot().active_cancellation_registrations, 0);
        let consumption = match &outcome {
            ActivationOutcome::Succeeded(success) => &success.consumption,
            ActivationOutcome::DeclaredError { consumption, .. }
            | ActivationOutcome::Failed { consumption, .. } => consumption,
        };
        assert!(accounting
            .finalize_at(Some(consumption), Instant::now())
            .violation()
            .is_none());
        drop(permit);
        Ok(outcome)
    }

    fn assert_clean(&self) {
        assert_eq!(self.quotas.usage().unwrap(), QuotaUsage::default());
        assert_eq!(self.quotas.retained_tenant_count().unwrap(), 0);
        assert_eq!(self.runner.snapshot().active_cancellation_registrations, 0);
        assert_eq!(self.runner.snapshot().running_invocations, 0);
        assert_eq!(self.pool.observations().queue_depth, 0);
    }
}

fn failure_code(outcome: &ActivationOutcome) -> Code {
    match outcome {
        ActivationOutcome::Failed { error, .. } => error.code,
        other => panic!("expected failure, got {other:?}"),
    }
}

#[tokio::test]
async fn runner_terminal_matrix_disposes_cells_before_quota_returns_to_baseline() {
    for mode in [
        Mode::Success,
        Mode::Declared,
        Mode::Trap,
        Mode::Deadline,
        Mode::Fuel,
        Mode::PlatformFailure,
        Mode::CleanupFailure,
    ] {
        let fixture = Fixture::new(mode, 1);
        let outcome = fixture.invoke(fixture.request("terminal")).await.unwrap();
        match mode {
            Mode::Success | Mode::CleanupFailure => {
                assert!(matches!(outcome, ActivationOutcome::Succeeded(_)))
            }
            Mode::Declared => assert!(matches!(outcome, ActivationOutcome::DeclaredError { .. })),
            Mode::Trap => assert_eq!(failure_code(&outcome), Code::GuestTrap),
            Mode::Deadline => assert_eq!(failure_code(&outcome), Code::DeadlineExceeded),
            Mode::Fuel => assert_eq!(failure_code(&outcome), Code::ResourceExhausted),
            Mode::PlatformFailure => assert_eq!(failure_code(&outcome), Code::Unavailable),
            Mode::Blocked => unreachable!(),
        }
        assert_eq!(fixture.backend.calls.load(Ordering::SeqCst), 1);
        assert_eq!(fixture.pool.observations().active_leases, 0);
        assert_eq!(
            fixture.pool.observations().quarantined,
            u32::from(matches!(mode, Mode::CleanupFailure))
        );
        assert_eq!(
            fixture.pool.observations().available,
            u32::from(!matches!(mode, Mode::CleanupFailure))
        );
        fixture.assert_clean();
    }
}

#[tokio::test]
async fn admission_rejection_never_calls_the_real_runner_or_cell_pool() {
    let fixture = Fixture::new(Mode::Success, 1);
    let before = fixture.pool.observations();
    let mut request = fixture.request("rejected");
    request.payload_bytes = 1025;
    assert_eq!(
        fixture.invoke(request).await.unwrap_err().code,
        Code::ResourceExhausted
    );
    assert_eq!(fixture.runner.snapshot().total_invocations, 0);
    assert_eq!(fixture.backend.calls.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.pool.observations(), before);
    fixture.assert_clean();
}

#[tokio::test]
async fn downstream_queue_failure_returns_the_admission_reservation() {
    let fixture = Fixture::new(Mode::Success, 0);
    let id = ActivationId("occupier".to_owned());
    let tenant = TenantId("alice".to_owned());
    let lease = fixture
        .pool
        .acquire(
            &id,
            &tenant,
            CellClass::Tiny,
            &fixture.quotas.policy().budget_ceiling,
        )
        .await
        .unwrap();
    let outcome = fixture
        .invoke(fixture.request("enqueue-failed"))
        .await
        .unwrap();
    assert_eq!(failure_code(&outcome), Code::ResourceExhausted);
    assert_eq!(fixture.backend.calls.load(Ordering::SeqCst), 0);
    fixture.assert_clean();
    fixture.pool.release(lease).await.unwrap();
    assert_eq!(fixture.pool.observations().available, 1);
}

#[tokio::test]
async fn cancellation_in_the_real_runner_releases_queued_and_running_quota() {
    for queued in [true, false] {
        let fixture = Fixture::new(Mode::Blocked, 1);
        let id = ActivationId("occupier".to_owned());
        let tenant = TenantId("alice".to_owned());
        let held = if queued {
            Some(
                fixture
                    .pool
                    .acquire(
                        &id,
                        &tenant,
                        CellClass::Tiny,
                        &fixture.quotas.policy().budget_ceiling,
                    )
                    .await
                    .unwrap(),
            )
        } else {
            None
        };
        let mut invocation = Box::pin(fixture.invoke(fixture.request("cancelled")));
        assert!(matches!(
            invocation
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop())),
            Poll::Pending
        ));
        assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
        assert_eq!(fixture.pool.observations().queue_depth, u32::from(queued));
        assert_eq!(
            fixture
                .runner
                .cancel(&ActivationId("cancelled".to_owned()), "stop")
                .await
                .unwrap(),
            CancelDisposition::Accepted
        );
        fixture.backend.resume.notify_one();
        let outcome = invocation.await.unwrap();
        assert_eq!(failure_code(&outcome), Code::Cancelled);
        fixture.assert_clean();
        if let Some(lease) = held {
            fixture.pool.release(lease).await.unwrap();
        }
        assert_eq!(fixture.pool.observations().available, 1);
    }
}

#[tokio::test]
async fn dropping_real_runner_futures_reclaims_quota_and_cancellation_without_reusing_uncertain_cells(
) {
    for queued in [true, false] {
        let fixture = Fixture::new(Mode::Blocked, 1);
        let id = ActivationId("occupier".to_owned());
        let tenant = TenantId("alice".to_owned());
        let held = if queued {
            Some(
                fixture
                    .pool
                    .acquire(
                        &id,
                        &tenant,
                        CellClass::Tiny,
                        &fixture.quotas.policy().budget_ceiling,
                    )
                    .await
                    .unwrap(),
            )
        } else {
            None
        };
        let mut invocation = Box::pin(fixture.invoke(fixture.request("dropped")));
        assert!(invocation
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
        drop(invocation);
        fixture.assert_clean();
        if let Some(lease) = held {
            fixture.pool.release(lease).await.unwrap();
        }
        assert_eq!(fixture.pool.observations().active_leases, 0);
        assert_eq!(fixture.pool.observations().quarantined, u32::from(!queued));
    }
}
