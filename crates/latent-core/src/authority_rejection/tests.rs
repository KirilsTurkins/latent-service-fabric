use super::*;

#[test]
fn scoped_rejection_is_irreversible_across_fresh_installation_without_other_tenant_churn() {
    let owner = AuthorityRejectionOwner::new(3).unwrap();
    let old = owner.install("a", "publication-a", None).unwrap();
    let sibling = owner.install("a", "publication-b", None).unwrap();
    let other = owner.install("b", "publication-a", None).unwrap();
    let observer = owner.observer();
    observer
        .reject(AuthorityRejection::Publication {
            tenant: Some("a"),
            publication: "publication-a",
        })
        .unwrap();
    assert!(!old.is_current());
    assert!(sibling.is_current());
    assert!(other.is_current());
    let fresh = owner.install("a", "publication-a", Some(&old)).unwrap();
    assert!(!old.is_current());
    assert!(fresh.is_current());
    observer
        .reject(AuthorityRejection::PolicyTenant("a"))
        .unwrap();
    assert!(!fresh.is_current());
    assert!(!sibling.is_current());
    assert!(other.is_current());
}

#[test]
fn bounded_replacement_reuses_one_slot_and_refuses_foreign_stamp_before_mutation() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let first = owner.install("a", "publication", None).unwrap();
    assert!(matches!(
        owner.install("b", "publication", None),
        Err(PlatformError {
            code: PlatformErrorCode::ResourceExhausted,
            ..
        })
    ));
    assert!(first.is_current());
    let foreign = AuthorityRejectionOwner::new(1).unwrap();
    let foreign_token = foreign.install("a", "publication", None).unwrap();
    assert!(owner
        .install("a", "publication", Some(&foreign_token))
        .is_err());
    assert!(foreign_token.is_current());
    let second = owner.install("a", "publication", Some(&first)).unwrap();
    assert!(!first.is_current());
    assert!(second.is_current());
    for _ in 0..64 {
        second.reject();
        let replacement = owner.install("a", "publication", None).unwrap();
        assert!(replacement.is_current());
        assert_eq!(owner.0.entries.lock().unwrap().len(), 1);
        drop(replacement);
    }
    assert_eq!(owner.0.entries.lock().unwrap().capacity(), 1);
}

#[test]
fn weak_observer_does_not_keep_retired_registry_or_current_stamps_alive() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    let observer = owner.observer();
    observer.reject(AuthorityRejection::OwnerRetired).unwrap();
    assert!(!token.is_current());
    assert!(owner.install("a", "publication", Some(&token)).is_err());
    drop(owner);
    assert!(!token.is_current());
    assert_eq!(
        observer
            .reject(AuthorityRejection::OwnerRetired)
            .unwrap_err()
            .code,
        PlatformErrorCode::Unavailable
    );
}

#[test]
fn observer_registration_is_once_only_and_refuses_late_exposure_and_contention() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let registration = AuthorityRejectionRegistration::default();
    registration.install(owner.observer()).unwrap();
    assert!(registration.observes(&owner.observer()));
    let foreign = AuthorityRejectionOwner::new(1).unwrap();
    assert!(!registration.observes(&foreign.observer()));
    assert_eq!(
        registration.install(owner.observer()).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    registration.expose().unwrap();
    let late = AuthorityRejectionRegistration::default();
    let guard = late.gate.lock().unwrap();
    assert!(late.expose().is_err());
    assert!(late.install(owner.observer()).is_err());
    drop(guard);
    late.expose().unwrap();
    assert_eq!(
        late.install(owner.observer()).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
}

#[test]
fn invalid_bounds_or_targets_leave_existing_original_token_current() {
    assert!(AuthorityRejectionOwner::new(0).is_err());
    assert!(AuthorityRejectionOwner::new(8193).is_err());
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    let observer = owner.observer();
    for tenant in ["", "line\nbreak"] {
        assert!(observer
            .reject(AuthorityRejection::PolicyTenant(tenant))
            .is_err());
    }
    assert!(owner
        .install(&"a".repeat(513), "publication", Some(&token))
        .is_err());
    assert!(owner.install("a", &"p".repeat(257), Some(&token)).is_err());
    assert!(token.is_current());
}

#[test]
fn poisoned_metadata_registry_rejects_original_tokens_and_fresh_installation() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    std::thread::scope(|scope| {
        assert!(scope
            .spawn(|| {
                let _guard = owner.0.entries.lock().unwrap();
                panic!("controlled metadata poison");
            })
            .join()
            .is_err());
    });
    assert!(!token.is_current());
    assert!(owner.install("a", "publication", Some(&token)).is_err());
    assert!(owner
        .observer()
        .reject(AuthorityRejection::OwnerRetired)
        .is_err());
}
