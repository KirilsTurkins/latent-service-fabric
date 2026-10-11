use super::*;

#[test]
fn actual_registry_capture_refuses_equal_foreign_owner_and_all_real_rejections() {
    let owner = AuthorityRejectionOwner::new(2).unwrap();
    let foreign = AuthorityRejectionOwner::new(2).unwrap();
    let first = owner.capture_control_generation().unwrap();
    let foreign_capture = foreign.capture_control_generation().unwrap();
    assert_eq!(first.generation(), foreign_capture.generation());
    assert_eq!(
        foreign
            .with_control_generation(&first, || ())
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    owner.with_control_generation(&first, || ()).unwrap();
    // The accepted policy mutation advances its real observer even when this
    // registry has not yet installed a row for the affected tenant.
    owner
        .observer()
        .reject(AuthorityRejection::PolicyTenant("uninstalled"))
        .unwrap();
    assert!(owner.with_control_generation(&first, || ()).is_err());
    let before_install = owner.capture_control_generation().unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    assert!(owner
        .with_control_generation(&before_install, || ())
        .is_err());
    let before_direct_rejection = owner.capture_control_generation().unwrap();
    token.reject();
    assert!(owner
        .with_control_generation(&before_direct_rejection, || ())
        .is_err());
    let before_retirement = owner.capture_control_generation().unwrap();
    owner
        .observer()
        .reject(AuthorityRejection::OwnerRetired)
        .unwrap();
    assert!(owner
        .with_control_generation(&before_retirement, || ())
        .is_err());
    assert!(owner.capture_control_generation().is_err());
}

#[test]
fn original_registry_metadata_fence_rejects_busy_and_is_held_through_acceptance() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let captured = owner.capture_control_generation().unwrap();
    {
        let _busy = owner.0.entries.try_lock().unwrap();
        assert!(owner.capture_control_generation().is_err());
        assert!(owner
            .with_control_generation(&captured, || panic!("busy callback ran"))
            .is_err());
    }
    owner
        .with_control_generation(&captured, || {
            assert!(matches!(
                owner.0.entries.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
        })
        .unwrap();
    owner.with_control_generation(&captured, || ()).unwrap();
}

#[test]
fn registry_generation_overflow_and_acceptance_unwind_permanently_refuse_original_owner() {
    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    owner.0.generation.store(u64::MAX, Ordering::Release);
    let captured = owner.capture_control_generation().unwrap();
    assert!(owner
        .observer()
        .reject(AuthorityRejection::PolicyTenant("other"))
        .is_err());
    assert!(!token.is_current());
    assert!(owner.with_control_generation(&captured, || ()).is_err());
    assert!(owner.install("a", "publication", Some(&token)).is_err());

    let owner = AuthorityRejectionOwner::new(1).unwrap();
    let token = owner.install("a", "publication", None).unwrap();
    let captured = owner.capture_control_generation().unwrap();
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        owner.with_control_generation(&captured, || panic!("controlled capture acceptance cut"))
    }))
    .is_err());
    assert!(!token.is_current());
    assert!(owner.capture_control_generation().is_err());
    assert!(owner.with_control_generation(&captured, || ()).is_err());
}
