use super::*;

#[tokio::test]
async fn actual_clock_rollback_remains_fatal_after_time_advances_again() {
    let owned = Owned::start().await;
    owned.clock.rewind_wall();
    let rejected = !owned.kernel.is_running(&owned.effects);
    owned.clock.advance(Duration::from_secs(2));
    let still_rejected = !owned.kernel.is_running(&owned.effects);
    let command_rejected = owned.effects.command_admission_source().capture().is_err();
    let retired = owned.retire().await;
    assert!(retired);
    assert!(rejected && still_rejected && command_rejected);
}

#[tokio::test]
async fn actual_coverage_expiry_remains_fatal_after_original_authority_renews() {
    let owned = Owned::start().await;
    owned.clock.advance(Duration::from_secs(5));
    let rejected = !owned.kernel.is_running(&owned.effects);
    let renewed = owned.authority.renew_clock_lease().is_ok();
    let still_rejected = !owned.kernel.is_running(&owned.effects);
    let retired = owned.retire().await;
    assert!(retired);
    assert!(renewed);
    assert!(rejected && still_rejected);
}

#[tokio::test]
async fn actual_authority_retirement_remains_fatal_to_liveness_and_admission() {
    let owned = Owned::start().await;
    owned.authority.retire();
    let rejected = !owned.kernel.is_running(&owned.effects);
    let command_rejected = owned.effects.command_admission_source().capture().is_err();
    let retired = owned.retire().await;
    assert!(retired);
    assert!(rejected && command_rejected);
}

#[tokio::test]
async fn actual_restore_review_rejects_liveness_and_an_original_writer_fence() {
    use std::sync::atomic::{AtomicUsize, Ordering};

    let owned = Owned::start().await;
    let original = owned.effects.command_admission_source().capture().unwrap();
    let entered = AtomicUsize::new(0);
    owned.effects.require_dispatcher_restore_review().unwrap();
    let clock_live = owned.kernel.clock.sample().is_ok();
    let rejected = !owned.kernel.is_running(&owned.effects);
    let current = original.with_current(|_, _| entered.fetch_add(1, Ordering::SeqCst));
    original.retire();
    let retired = owned.retire().await;
    assert!(retired);
    assert!(clock_live && rejected && current.is_err());
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn actual_closed_dispatcher_and_quarantined_store_remain_fatal() {
    for close_dispatcher in [true, false] {
        let owned = Owned::start().await;
        if close_dispatcher {
            owned.effects.close();
        } else {
            owned.kernel.store.quarantine();
        }
        let rejected = !owned.kernel.is_running(&owned.effects);
        let command_rejected = owned.effects.command_admission_source().capture().is_err();
        let retired = owned.retire().await;
        assert!(retired);
        assert!(rejected && command_rejected);
    }
}

#[tokio::test]
async fn busy_message_lookalikes_never_supply_positive_liveness() {
    let genuine_shape = PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "admission-authority-busy".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), "admission-authority-busy".into())].into(),
        }],
    };
    let mut wrong_code = genuine_shape.clone();
    wrong_code.code = PlatformErrorCode::PermissionDenied;
    let mut wrong_retryability = genuine_shape.clone();
    wrong_retryability.retryable = false;
    let mut message_only = genuine_shape.clone();
    message_only.details.clear();
    let mut wrong_kind = genuine_shape.clone();
    wrong_kind.details[0].kind = "untrusted.currentness".into();
    let mut extra_field = genuine_shape.clone();
    extra_field.details[0]
        .fields
        .insert("other".into(), "value".into());
    let mut duplicate = genuine_shape.clone();
    duplicate.details.push(duplicate.details[0].clone());
    let mut wrong_reason = genuine_shape;
    wrong_reason.details[0]
        .fields
        .insert("reason".into(), "admission-control-busy".into());
    for failure in [
        wrong_code,
        wrong_retryability,
        message_only,
        wrong_kind,
        extra_field,
        duplicate,
        wrong_reason,
    ] {
        let owned = Owned::start().await;
        // Fabricated failures are negative controls only. Positive busy cases
        // above are produced by the actual original authority high-water race.
        owned.clock.fail_next(failure);
        let rejected = !owned.kernel.is_running(&owned.effects);
        let retired = owned.retire().await;
        assert!(retired);
        assert!(rejected);
    }
}
