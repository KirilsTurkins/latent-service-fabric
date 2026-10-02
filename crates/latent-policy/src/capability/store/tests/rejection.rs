use super::*;
use latent_core::authority_rejection::AuthorityRejectionOwner;

#[test]
fn accepted_policy_withdrawal_reapproval_and_receipt_replay_never_revive_original_stamp() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let effects = AuthorityRejectionOwner::new(2).unwrap();
    store
        .install_rejection_observer(effects.observer())
        .unwrap();
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    let original = effects.install("a", "publication-a", None).unwrap();
    let other = effects.install("b", "publication-b", None).unwrap();
    assert!(mutate(&store, "p", "wrong-cas", 0, None).is_err());
    assert!(store
        .mutate(
            MutationRequest {
                operation_id: "preflight-refused",
                expected_revision: 2,
                document: None,
                ..request(&bytes)
            },
            deadline(),
            |_| Err(crate::capability::capacity()),
        )
        .is_err());
    assert!(original.is_current());
    let withdrawn = mutate(&store, "p", "withdraw", 2, None)
        .unwrap()
        .value()
        .clone();
    assert!(!original.is_current());
    assert!(other.is_current());
    let approved = mutate(&store, "p", "reapprove", withdrawn.revision, Some(&bytes))
        .unwrap()
        .value()
        .clone();
    let fresh = effects
        .install("a", "publication-a", Some(&original))
        .unwrap();
    assert!(!original.is_current());
    assert!(fresh.is_current());
    assert_eq!(
        mutate(&store, "p", "withdraw", 2, None).unwrap().value(),
        &withdrawn
    );
    assert_eq!(
        mutate(&store, "p", "reapprove", withdrawn.revision, Some(&bytes))
            .unwrap()
            .value(),
        &approved
    );
    assert!(
        fresh.is_current(),
        "historical receipt recovery is not a new acceptance"
    );
    assert!(other.is_current());
    drop(store);
    assert!(!fresh.is_current());
}

#[test]
fn every_unknown_policy_flush_cut_keeps_original_stamp_rejected_after_restart() {
    for point in 1..=6 {
        let fixture = Fixture::new();
        let store = fixture.store(PolicyStoreLimits::default());
        let effects = AuthorityRejectionOwner::new(1).unwrap();
        store
            .install_rejection_observer(effects.observer())
            .unwrap();
        let bytes = serde_json::to_vec(&policy()).unwrap();
        mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
        let original = effects.install("a", "publication-a", None).unwrap();
        store
            .state
            .lock()
            .unwrap()
            .ledger
            .as_ref()
            .unwrap()
            .fault
            .store(point, Ordering::Release);
        assert!(mutate(&store, "p", "withdraw", 2, None).is_err());
        assert!(!original.is_current());
        drop(store);
        let reopened = fixture.store(PolicyStoreLimits::default());
        assert_eq!(
            reopened
                .outcome("a", "withdraw", deadline())
                .unwrap()
                .value()
                .is_some(),
            point >= 3
        );
        assert!(
            !original.is_current(),
            "fresh ledger ownership cannot reset an old token"
        );
    }
}

#[test]
fn policy_observer_installation_is_once_before_real_owner_exposure() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let effects = AuthorityRejectionOwner::new(1).unwrap();
    store
        .install_rejection_observer(effects.observer())
        .unwrap();
    assert_eq!(
        store
            .install_rejection_observer(effects.observer())
            .unwrap_err()
            .code,
        PlatformErrorCode::StateConflict
    );
    store.reserve_inspection().unwrap();
    assert!(store
        .install_rejection_observer(effects.observer())
        .is_err());
    drop(store);
    let late = fixture.store(PolicyStoreLimits::default());
    late.reserve_inspection().unwrap();
    assert_eq!(
        late.install_rejection_observer(effects.observer())
            .unwrap_err()
            .code,
        PlatformErrorCode::StateConflict
    );
}
