use super::*;
use latent_state::{
    namespace::{history::HistoryStatus, NamespaceStatus},
    recovery::RecoveryGuard,
};

pub(super) async fn observe(source: &OfflineRecoverySource) -> NamespaceRecoveryView {
    source
        .inspect_namespace(
            "operator".into(),
            latent_core::StateNamespaceId("orders".into()),
            physical::deadline(),
        )
        .unwrap()
        .await
        .unwrap()
}

fn request(observed: &NamespaceRecoveryView, operation: &str) -> NamespaceResumeRequest {
    NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: operation.into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token().unwrap(),
        review_digest: [71; 32],
    }
}

pub(super) async fn resume(source: &OfflineRecoverySource, operation: &str) {
    let observed = observe(source).await;
    source
        .resume_namespace(request(&observed, operation), physical::deadline())
        .unwrap()
        .await
        .unwrap();
}

pub(super) async fn reconcile(
    source: &OfflineRecoverySource,
    codecs: &codecs::Codecs,
    guard: &RecoveryGuard,
    endpoint: &Endpoint,
    remote_receipt: &str,
) -> NamespaceRecoveryView {
    let observed = observe(source).await;
    assert_eq!(
        observed.history.status,
        HistoryStatus::ReconciliationRequired
    );
    assert_eq!(
        source
            .resume_namespace(request(&observed, "premature-resume"), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    let mut request = RecoveryReviewRequest {
        operator_id: "operator".into(),
        expected_guard: guard.clone(),
        review_digest: [69; 32],
    };
    assert_eq!(
        source
            .review_reconciliation(request.clone(), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    request.review_digest = codecs.approve_reconciliation(guard, remote_receipt);
    let accepted = source
        .review_reconciliation(request, physical::deadline())
        .unwrap()
        .await
        .unwrap();
    assert_eq!(accepted.status(), RecoveryStatus::ReviewAccepted);
    let observed = observe(source).await;
    assert_eq!(observed.namespace.status, NamespaceStatus::Quiescing);
    assert_eq!(
        observed.history.status,
        HistoryStatus::ReconciliationRequired
    );
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    observed
}

pub(super) async fn resume_with_current_authority(
    source: &OfflineRecoverySource,
    fixture: &Fixture,
    endpoint: &Endpoint,
) {
    let observed = observe(source).await;
    let request = request(&observed, "approved-restored-resume");
    let mut revoked = fixture.rule.clone();
    revoked.enabled = false;
    fixture.authority.publish(revoked).unwrap();
    assert_eq!(
        source
            .resume_namespace(request.clone(), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    assert_eq!(
        observe(source).await.history.status,
        HistoryStatus::ReconciliationRequired
    );
    assert_eq!(endpoint.counter(), 1);
    fixture.authority.publish(fixture.rule.clone()).unwrap();
    // Backward local time does not expire identity/history or permit resume.
    fixture.clock.0.store(99, Ordering::SeqCst);
    assert_eq!(
        source
            .resume_namespace(request.clone(), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    assert_eq!(
        observe(source).await.history.status,
        HistoryStatus::ReconciliationRequired
    );
    assert_eq!(endpoint.counter(), 1);
    fixture.clock.0.store(100, Ordering::SeqCst);
    let resumed = source
        .resume_namespace(request.clone(), physical::deadline())
        .unwrap()
        .await
        .unwrap();
    let replay = source
        .resume_namespace(request, physical::deadline())
        .unwrap()
        .await
        .unwrap();
    assert_eq!(replay.encode().unwrap(), resumed.encode().unwrap());
    assert_eq!(observe(source).await.history.status, HistoryStatus::Ready);
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
}
