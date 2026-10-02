use super::{
    durable::{commit, open, Root},
    *,
};
use latent_core::authority_rejection::AuthorityRejectionOwner;

#[test]
fn accepted_lifecycle_change_rejects_only_exact_scoped_publication_and_not_receipt_replay() {
    let root = Root::new();
    let mut first = identity(b"first");
    first.scope = LifecycleScope::Tenant(latent_core::TenantId("a".into()));
    let mut other = identity(b"other");
    other.scope = LifecycleScope::Tenant(latent_core::TenantId("b".into()));
    let store = open(
        &root,
        &[first.clone(), other.clone()],
        LifecycleLimits::default(),
    );
    let effects = AuthorityRejectionOwner::new(2).unwrap();
    store
        .handle()
        .install_rejection_observer(effects.observer())
        .unwrap();
    let original = effects
        .install("a", first.publication().unwrap().id.as_str(), None)
        .unwrap();
    let unaffected = effects
        .install("b", other.publication().unwrap().id.as_str(), None)
        .unwrap();
    let old = store.record(&first.release).unwrap().unwrap();
    let receipt = revocation(&old, "withdraw");
    commit(&store, receipt.clone(), None).unwrap();
    assert!(!original.is_current());
    assert!(unaffected.is_current());
    let read_stamp = effects
        .install(
            "a",
            first.publication().unwrap().id.as_str(),
            Some(&original),
        )
        .unwrap();
    commit(&store, receipt, None).unwrap();
    assert!(
        read_stamp.is_current(),
        "historical replay accepts no new lifecycle mutation"
    );
    assert!(unaffected.is_current());
    // The real lifecycle is terminal. A copied old admitted row cannot reopen it.
    assert!(commit(
        &store,
        publication(&first, "stale-reapprove"),
        Some(first.clone())
    )
    .is_err());
    assert!(read_stamp.is_current());
    assert!(!original.is_current());
    drop(store);
    let reopened = open(&root, &[first.clone(), other], LifecycleLimits::default());
    assert_eq!(
        reopened.record(&first.release).unwrap().unwrap().state,
        ReleaseLifecycleState::Revoked
    );
    assert!(!original.is_current());
}

#[test]
fn uncertain_lifecycle_persistence_never_reopens_rejected_original_stamp_after_roll_forward() {
    for point in 1..=4 {
        let root = Root::new();
        let first = identity(b"fault");
        let store = open(
            &root,
            std::slice::from_ref(&first),
            LifecycleLimits::default(),
        );
        let effects = AuthorityRejectionOwner::new(1).unwrap();
        store
            .handle()
            .install_rejection_observer(effects.observer())
            .unwrap();
        let original = effects
            .install("a", first.publication().unwrap().id.as_str(), None)
            .unwrap();
        let old = store.record(&first.release).unwrap().unwrap();
        persistence::FAIL.with(|value| value.set(point));
        assert!(commit(&store, revocation(&old, "withdraw"), None).is_err());
        assert!(!original.is_current());
        drop(store);
        let reopened = open(
            &root,
            std::slice::from_ref(&first),
            LifecycleLimits::default(),
        );
        assert_eq!(
            reopened.record(&first.release).unwrap().unwrap().state,
            ReleaseLifecycleState::Revoked
        );
        assert!(!original.is_current());
    }
}

#[test]
fn lifecycle_observer_registration_refuses_duplicate_late_or_retired_actual_owner() {
    let root = Root::new();
    let first = identity(b"registration");
    let effects = AuthorityRejectionOwner::new(1).unwrap();
    let store = open(
        &root,
        std::slice::from_ref(&first),
        LifecycleLimits::default(),
    );
    let handle = store.handle();
    handle
        .install_rejection_observer(effects.observer())
        .unwrap();
    assert!(handle
        .install_rejection_observer(effects.observer())
        .is_err());
    let eligibility = store.eligibility(&first.release, None).unwrap();
    assert!(handle
        .install_rejection_observer(effects.observer())
        .is_err());
    drop(store);
    assert!(handle
        .install_rejection_observer(effects.observer())
        .is_err());
    let reopened = open(
        &root,
        std::slice::from_ref(&first),
        LifecycleLimits::default(),
    );
    reopened.eligibility(&first.release, None).unwrap();
    assert!(reopened
        .handle()
        .install_rejection_observer(effects.observer())
        .is_err());
    assert!(eligibility.check_current().is_err());
}
