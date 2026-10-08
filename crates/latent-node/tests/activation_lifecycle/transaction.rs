use super::{
    model::request,
    support::{error, finish, Harness},
};
use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{ActivationBudget, BoxFuture, BudgetProfile, PlatformError, PlatformErrorCode};
use latent_node::{TransactionActivationAdmission, TransactionAdmission};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

struct DeniedAdmission(AtomicUsize);
impl TransactionActivationAdmission for DeniedAdmission {
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(async move {
            assert_eq!(budget.profile(), BudgetProfile::Phase4);
            assert!(envelope.resolved_revision.is_some());
            assert_eq!(budget.granted().cpu_fuel, envelope.budget.cpu_fuel);
            self.0.fetch_add(1, Ordering::Relaxed);
            Err(error(
                PlatformErrorCode::PermissionDenied,
                "current namespace authority denied",
            ))
        })
    }
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
