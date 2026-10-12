use super::*;
use latent_core::{
    native_capacity::{NativeBufferClass, NativeCapacityLimits, NativeCapacityPartition},
    test_support::TestClock,
    ActivationClock,
};
use std::time::Duration;

#[test]
fn shared_recovery_admission_keeps_exact_capacities_and_does_not_borrow_ordinary_slots() {
    let limits = NativeCapacityLimits {
        ordinary: NativeCapacityPartition {
            slots: 1,
            bytes: 3_072,
            maximum_reservation_bytes: 3_072,
        },
        recovery: NativeCapacityPartition {
            slots: 1,
            bytes: 4_096,
            maximum_reservation_bytes: 4_096,
        },
        maximum_lifetime: Duration::from_secs(30),
    };
    let owner = NativeCapacityOwner::new(limits).unwrap();
    let admission = StateManagementRecoveryAdmission::new(owner.clone());
    let deadline = Instant::now() + Duration::from_secs(10);
    let ordinary = owner
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 1_024,
                ..NativeReservationRequest::default()
            },
            deadline,
        )
        .unwrap();
    let buffer = ordinary
        .allocate_bytes(NativeBufferClass::Request, 1_024)
        .unwrap();
    drop(ordinary);
    owner.close_ordinary();
    let recovery = admission.reserve_recovery(32, 64, 128, deadline).unwrap();
    assert_eq!(recovery.reserved_response_bytes(), 128);
    let held = owner.snapshot().unwrap();
    assert_eq!(held.ordinary.bytes, 3_072);
    assert_eq!(held.recovery.bytes, 2_272);
    assert_eq!(
        admission
            .reserve_recovery(0, 0, 0, deadline)
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let physical = Arc::clone(&recovery);
    drop(recovery);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    let mut calls = 0;
    physical.with_live(&mut || calls += 1).unwrap();
    assert_eq!(calls, 1);
    drop(physical);
    assert_eq!(owner.snapshot().unwrap().recovery.bytes, 0);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    drop(buffer);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn recovery_original_deadline_and_closed_owner_deny_without_refunding_retained_capacity() {
    let clock = TestClock::new(100, Instant::now(), 1);
    let owner =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    let admission = StateManagementRecoveryAdmission::new(owner.clone());
    let deadline = clock.monotonic_now() + Duration::from_secs(10);
    let recovery = admission.reserve_recovery(32, 64, 128, deadline).unwrap();
    clock.set_wall_unix_millis(u64::MAX);
    recovery.with_live(&mut || {}).unwrap();
    clock.advance(Duration::from_secs(10));
    assert_eq!(
        recovery
            .with_live(&mut || panic!("expired native fence ran"))
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(owner.snapshot().unwrap().recovery.bytes, 2_272);
    drop(recovery);
    let current = admission
        .reserve_recovery(32, 64, 128, clock.monotonic_now() + Duration::from_secs(10))
        .unwrap();
    owner.close();
    assert_eq!(
        current
            .with_live(&mut || panic!("closed native fence ran"))
            .unwrap_err()
            .code,
        PlatformErrorCode::Unavailable
    );
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(current);
    assert!(owner.snapshot().unwrap().physically_retired());
}
