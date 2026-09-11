use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Instant;

use latent_activation::{
    ActivationEnvelope, ActivationManager, ActivationOutcome, ActivationSuccess,
};
use latent_core::{
    ActivationClock, BudgetConsumption, CancelDisposition, ClockSample, EffectiveActivationBudget,
};
use latent_executor::ExecutionCleanup;

use super::*;
use crate::{ActivationBudgetPolicy, BudgetedActivationManager};

mod owned;
mod support;
use support::{budget, request};

struct Clock(ClockSample);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        self.0
    }
    fn monotonic_now(&self) -> Instant {
        self.0.monotonic()
    }
}

struct Cancellation {
    id: ActivationId,
    accounting: Option<ActivationBudget>,
}
impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        self.accounting.as_ref()
    }
}

#[derive(Default)]
struct Recorder {
    calls: AtomicU64,
    seen: Mutex<Vec<Option<ActivationBudget>>>,
}

impl Recorder {
    fn run(&self, cancellation: &dyn ExecutionCancellation) -> GuestOutcome {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let accounting = cancellation.budget_accounting().cloned();
        if let Some(budget) = &accounting {
            assert_eq!(cancellation.effective_deadline(), Some(budget.deadline()));
            budget.consume_cpu_fuel(3).expect("CPU charge");
            budget
                .reserve_log_bytes(7)
                .expect("log capacity")
                .commit()
                .expect("accepted log");
        }
        self.seen.lock().expect("observations").push(accounting);
        GuestOutcome::Returned {
            output: Vec::new(),
            output_media_type: "test".to_owned(),
            consumption: BudgetConsumption {
                cpu_fuel: 3,
                log_bytes: 0,
                ..BudgetConsumption::default()
            },
        }
    }
}

impl ExecutionBackend for Recorder {
    fn backend_id(&self) -> &'static str {
        "test"
    }
    fn preparation_key(&self, release: &ReleaseDigest) -> Result<PreparationKey, PlatformError> {
        let mut key = request().prepared.key;
        key.release = release.clone();
        Ok(key)
    }
    fn invoke_prepared_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        prepared: PreparedUse,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let (descriptor, _owner) = prepared
                .into_parts::<owned::Owner>()
                .expect("exact owner forwarded");
            assert_eq!(descriptor, request.prepared);
            ExecutionReport::quarantine(Ok(self.run(cancellation)), "fixture cleanup proof")
        })
    }
    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async { Ok(request().prepared) })
    }
    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move { Ok(self.run(cancellation)) })
    }
    fn invoke_contained<'a>(
        &'a self,
        _request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            ExecutionReport::quarantine(Ok(self.run(cancellation)), "fixture cleanup proof")
        })
    }
    fn release(&self, _prepared: PreparedComponent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async { Ok(()) })
    }
}

struct Manager {
    backend: Arc<BudgetedExecutionBackend>,
    registry: ActivationBudgetRegistry,
    supplied: bool,
    foreign: bool,
}

impl ActivationManager for Manager {
    fn invoke(&self, envelope: ActivationEnvelope) -> BoxFuture<'_, ActivationOutcome> {
        Box::pin(async move {
            let mut request = request();
            request.budget = envelope.budget.clone();
            request.activation = envelope;
            let owner = self
                .registry
                .get(&request.activation.activation_id)
                .expect("registered owner");
            let accounting = if self.foreign {
                Some(ActivationBudget::new(EffectiveActivationBudget {
                    budget: owner.granted().clone(),
                    deadline: owner.deadline().clone(),
                }))
            } else if self.supplied {
                Some(owner.clone())
            } else {
                None
            };
            let cancellation = Cancellation {
                id: request.activation.activation_id.clone(),
                accounting,
            };
            match self.backend.invoke(request, &cancellation).await {
                Ok(GuestOutcome::Returned {
                    output,
                    output_media_type,
                    consumption,
                }) => ActivationOutcome::Succeeded(ActivationSuccess {
                    output,
                    output_media_type,
                    consumption,
                    committed_state_version: None,
                    effect_ids: Vec::new(),
                    metadata: latent_core::Metadata::new(),
                }),
                Err(error) => ActivationOutcome::Failed {
                    error,
                    terminal_state: latent_core::ActivationTerminalState::Rejected,
                    consumption: BudgetConsumption::default(),
                },
                _ => panic!("fixture only returns a payload"),
            }
        })
    }
    fn cancel<'a>(
        &'a self,
        _activation_id: &'a ActivationId,
        _reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        Box::pin(async { Ok(CancelDisposition::NotFound) })
    }
}

fn assemble(supplied: bool, foreign: bool) -> (BudgetedActivationManager<Manager>, Arc<Recorder>) {
    let recorder = Arc::new(Recorder::default());
    let registry = ActivationBudgetRegistry::default();
    let backend = Arc::new(BudgetedExecutionBackend::new(
        recorder.clone(),
        registry.clone(),
    ));
    let inner = Arc::new(Manager {
        backend,
        registry: registry.clone(),
        supplied,
        foreign,
    });
    let manager = BudgetedActivationManager::new_with_clock_and_budget_registry(
        inner,
        ActivationBudgetPolicy::new(budget(), budget()),
        Arc::new(Clock(ClockSample::new(1_000, Instant::now()))),
        registry,
    )
    .expect("manager");
    (manager, recorder)
}

#[tokio::test]
async fn existing_manager_and_backend_share_one_terminal_log_ledger() {
    for supplied in [false, true] {
        let (manager, recorder) = assemble(supplied, false);
        let ActivationOutcome::Succeeded(outcome) = manager.invoke(request().activation).await
        else {
            panic!("successful execution")
        };
        assert_eq!(outcome.consumption.cpu_fuel, 3);
        assert_eq!(outcome.consumption.log_bytes, 7);
        assert_eq!(manager.budget_snapshot().active_registrations, 0);
        let seen = recorder.seen.lock().expect("observations");
        let captured = seen[0].as_ref().expect("shared handle");
        assert_eq!(captured.finalized().expect("owner finalized").log_bytes, 7);
        assert_eq!(captured.outstanding_reservations(), 0);
        assert_eq!(recorder.calls.load(Ordering::Relaxed), 1);
    }
}

#[tokio::test]
async fn a_different_supplied_owner_is_rejected_before_backend_execution() {
    let (manager, recorder) = assemble(true, true);
    let ActivationOutcome::Failed { error, .. } = manager.invoke(request().activation).await else {
        panic!("owner mismatch")
    };
    assert_eq!(error.message, "execution-budget-owner-mismatch");
    assert_eq!(recorder.calls.load(Ordering::Relaxed), 0);
    assert_eq!(manager.budget_snapshot().active_registrations, 0);
}

#[tokio::test]
async fn direct_provided_handles_and_backend_cleanup_proofs_are_preserved() {
    let recorder = Arc::new(Recorder::default());
    let backend =
        BudgetedExecutionBackend::new(recorder.clone(), ActivationBudgetRegistry::default());
    let request = request();
    let grant = EffectiveActivationBudget::admit_at(
        &request.budget,
        &request.budget,
        &request.budget,
        None,
        ClockSample::new(1_000, Instant::now()),
    )
    .expect("grant");
    let owner = ActivationBudget::new(grant);
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        accounting: Some(owner.clone()),
    };
    let report = backend.invoke_contained(request, &cancellation).await;
    assert!(matches!(
        report.cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
    assert!(recorder.seen.lock().expect("observations")[0]
        .as_ref()
        .expect("captured")
        .is_same_instance(&owner));
    assert!(
        owner.finalization().is_none(),
        "adapter does not own finalization"
    );
}

#[tokio::test]
async fn absent_accounting_remains_optional_and_wrong_cancellation_id_is_rejected() {
    let recorder = Arc::new(Recorder::default());
    let backend =
        BudgetedExecutionBackend::new(recorder.clone(), ActivationBudgetRegistry::default());
    let request = request();
    let mut cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        accounting: None,
    };
    backend
        .invoke(request.clone(), &cancellation)
        .await
        .expect("legacy direct caller");
    assert!(recorder.seen.lock().expect("observations")[0].is_none());
    cancellation.id.0 = "other".to_owned();
    let report = backend.invoke_contained(request, &cancellation).await;
    assert_eq!(
        report.outcome.expect_err("wrong ID").code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(recorder.calls.load(Ordering::Relaxed), 1);
}
