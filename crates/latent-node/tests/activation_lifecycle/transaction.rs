use super::{
    model::request,
    support::{error, finish, Harness},
};
use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{ActivationBudget, BoxFuture, BudgetProfile, PlatformError, PlatformErrorCode};
use latent_node::{
    TransactionActivationAdmission, TransactionAdmission, TransactionAdmissionKind,
    TransactionCompletion,
};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

struct DeniedAdmission(AtomicUsize);
impl TransactionActivationAdmission for DeniedAdmission {
    fn preflight<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            assert_eq!(budget.profile(), BudgetProfile::Phase4);
            assert!(!budget.descendant_is_cancelled());
            assert_eq!(budget.descendant_snapshot().unwrap().live_descendants, 0);
            assert!(envelope.resolved_revision.is_some());
            assert_eq!(budget.granted().cpu_fuel, envelope.budget.cpu_fuel);
            self.0.fetch_add(1, Ordering::Relaxed);
            Err(error(
                PlatformErrorCode::PermissionDenied,
                "current namespace authority denied",
            ))
        })
    }

    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(async move {
            assert_eq!(budget.profile(), BudgetProfile::Phase4);
            assert!(!budget.descendant_is_cancelled());
            assert!(envelope.resolved_revision.is_some());
            assert_eq!(budget.granted().cpu_fuel, envelope.budget.cpu_fuel);
            Err(error(
                PlatformErrorCode::PermissionDenied,
                "current namespace authority denied",
            ))
        })
    }
}

struct ExistingLookup(AtomicUsize);
impl TransactionActivationAdmission for ExistingLookup {
    fn kind(&self) -> TransactionAdmissionKind {
        TransactionAdmissionKind::ResultLookup
    }

    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(async move {
            assert_eq!(budget.profile(), BudgetProfile::Phase4);
            assert!(!budget.descendant_is_cancelled());
            assert_eq!(budget.descendant_snapshot().unwrap().live_descendants, 0);
            assert!(envelope.resolved_revision.is_some());
            self.0.fetch_add(1, Ordering::Relaxed);
            Ok(TransactionAdmission::Existing(Box::new(
                TransactionCompletion::ordinary(ActivationOutcome::Failed {
                    terminal_state: latent_core::ActivationTerminalState::Rejected,
                    error: error(PlatformErrorCode::NotFound, "original-command-not-found"),
                    consumption: latent_core::BudgetConsumption::default(),
                }),
            )))
        })
    }
}

struct AwaitOriginalRootCancellation(tokio::sync::Notify);
impl TransactionActivationAdmission for AwaitOriginalRootCancellation {
    fn preflight<'a>(
        &'a self,
        _envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            assert!(!budget.descendant_is_cancelled());
            assert_eq!(budget.descendant_snapshot().unwrap().live_descendants, 0);
            self.0.notify_one();
            budget.descendant_cancelled().await;
            assert!(budget.descendant_is_cancelled());
            Err(error(PlatformErrorCode::Cancelled, "original root stopped"))
        })
    }

    fn admit<'a>(
        &'a self,
        _envelope: &'a ActivationEnvelope,
        _budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(async { panic!("cancelled preflight cannot publish a claim") })
    }
}

#[tokio::test]
async fn managed_phase4_root_executes_once_with_the_original_bound_cancellation_owner() {
    let harness = Harness::transaction_profile();
    let receipt = finish(
        harness
            .manager
            .start(request("bound-phase4-root"))
            .expect("accepted root identity"),
    )
    .await;
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 1);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 1);
    harness.assert_idle();
}

#[tokio::test]
async fn transaction_preflight_observes_original_root_cancellation_before_claim_or_cell() {
    let harness = Harness::transaction_profile();
    let admission = Arc::new(AwaitOriginalRootCancellation(tokio::sync::Notify::new()));
    let mut handle = Box::pin(
        harness
            .manager
            .start_transaction_with_deadline(
                request("cancel-bound-transaction"),
                None,
                admission.clone(),
            )
            .expect("accepted original root"),
    );
    super::support::pending(handle.as_mut()).await;
    tokio::time::timeout(std::time::Duration::from_secs(5), admission.0.notified())
        .await
        .unwrap();
    assert_eq!(
        harness
            .manager
            .cancel_for(
                &latent_core::TenantId(super::model::TENANT.into()),
                &latent_core::ActivationId("cancel-bound-transaction".into()),
                "before command claim",
            )
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    let receipt = finish(handle).await;
    assert!(matches!(
        receipt.outcome,
        ActivationOutcome::Failed { error, .. } if error.code == PlatformErrorCode::Cancelled
    ));
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}

#[tokio::test]
async fn result_lookup_uses_original_admission_without_component_preparation_or_guest_work() {
    let harness = Harness::transaction_profile();
    let lookup = Arc::new(ExistingLookup(AtomicUsize::new(0)));
    let receipt = finish(
        harness
            .manager
            .start_transaction_with_deadline(request("finite-result-lookup"), None, lookup.clone())
            .expect("accepted original identity"),
    )
    .await;
    let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
        panic!("original lookup failure")
    };
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    assert_eq!(lookup.0.load(Ordering::Relaxed), 1);
    assert!(receipt.transaction.is_none());
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    assert_eq!(
        harness
            .backend
            .materialization_calls
            .load(Ordering::Relaxed),
        0
    );
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}

#[tokio::test]
async fn namespace_admission_runs_on_the_original_ledger_before_any_preparation_or_cell() {
    let harness = Harness::transaction_profile();
    let admission = Arc::new(DeniedAdmission(AtomicUsize::new(0)));
    let handle = harness
        .manager
        .start_transaction_with_deadline(request("transaction-denied"), None, admission.clone())
        .expect("accepted identity");
    let receipt = finish(handle).await;
    let ActivationOutcome::Failed { error: failure, .. } = receipt.outcome else {
        panic!("denial")
    };
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(admission.0.load(Ordering::Relaxed), 1);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}

#[tokio::test]
async fn ordinary_admission_cannot_install_state_by_selecting_a_transaction_entry_point() {
    let harness = Harness::standard();
    let admission = Arc::new(DeniedAdmission(AtomicUsize::new(0)));
    let receipt = finish(
        harness
            .manager
            .start_transaction_with_deadline(
                request("transaction-unconfigured"),
                None,
                admission.clone(),
            )
            .expect("identity"),
    )
    .await;
    let ActivationOutcome::Failed { error: failure, .. } = receipt.outcome else {
        panic!("denial")
    };
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(admission.0.load(Ordering::Relaxed), 0);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}
