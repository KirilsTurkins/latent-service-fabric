//! Actual clock imports and the production signed-currentness mutex, not a
//! synthetic Busy provider. Every attempted guest invocation runs once.
#![cfg(target_os = "linux")]
#[path = "broker/component.rs"]
mod component;
#[path = "broker/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "clock_admission/signed.rs"]
mod signed;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::*;
use std::{
    future::Future,
    sync::Mutex,
    task::{Context, Poll, Waker},
};

#[tokio::test]
async fn actual_clock_waits_on_original_grant_and_samples_each_import_once() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-contention");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    assert!(invocation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert!(held.lock().unwrap().is_some());
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    assert_eq!(f.broker.snapshot().sessions, 1);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    held.lock().unwrap().take().unwrap().release();
    let report = invocation.await;
    let GuestOutcome::Returned { consumption, .. } = report.outcome.unwrap() else {
        panic!("two actual clocks must finish");
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 2);
    let finalization = control
        .budget
        .finalize_at(Some(&consumption), Instant::now());
    assert!(finalization.violation().is_none());
    assert_eq!(
        finalization.consumption().cpu_fuel,
        consumption.cpu_fuel + 200
    );
    f.idle();
}

#[tokio::test]
async fn legacy_clock_without_explicit_timer_still_fails_closed_on_real_fence() {
    let signed = signed::Fixture::new(false).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-legacy");
    let report = f.backend.invoke_contained(request, &control).await;
    held.lock().unwrap().take().unwrap().release();
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    let GuestOutcome::Trapped { trap, .. } = report.outcome.unwrap() else {
        panic!("legacy import must fail closed");
    };
    assert_eq!(
        trap.metadata
            .get("admissionCurrentnessReason")
            .map(String::as_str),
        Some("admission-authority-busy")
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
}

#[tokio::test]
async fn dropping_actual_clock_wait_drops_store_and_all_pending_owners() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-drop");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    assert!(invocation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert!(held.lock().unwrap().is_some());
    drop(invocation);
    held.lock().unwrap().take().unwrap().release();
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.idle();
}

#[tokio::test]
async fn clock_wait_never_replaces_a_revoked_original_policy() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-revoked");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    assert!(invocation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    held.lock().unwrap().take().unwrap().release();
    fixture::revoke(&f.policies);
    let report = invocation.await;
    assert!(matches!(
        report.outcome.unwrap(),
        GuestOutcome::Trapped { .. }
    ));
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
}

#[tokio::test]
async fn clock_wait_does_not_renew_an_expired_original_admission_lease() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-expired-lease");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    assert!(invocation
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    signed.expire_original_lease();
    held.lock().unwrap().take().unwrap().release();
    let report = invocation.await;
    let GuestOutcome::Trapped { trap, .. } = report.outcome.unwrap() else {
        panic!("original lease must remain expired");
    };
    assert_eq!(
        trap.metadata
            .get("admissionCurrentnessReason")
            .map(String::as_str),
        Some("admission-clock-lease-uncovered")
    );
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
}
