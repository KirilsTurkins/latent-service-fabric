//! Actual clock imports and the production signed-currentness mutex, not a
//! synthetic Busy provider. Every attempted guest invocation runs once.
#![cfg(target_os = "linux")]
#[path = "broker/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "broker/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "clock_admission/monotonic.rs"]
mod monotonic;
#[path = "clock_admission/signed.rs"]
mod signed;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::*;
use std::{future::Future, pin::Pin, sync::Mutex, task::Poll};

async fn pending_at_fence(
    mut invocation: Pin<&mut impl Future<Output = latent_executor::ExecutionReport>>,
    held: &Arc<Mutex<Option<signed::Fence>>>,
) {
    // Readiness itself can yield before the Store exists. Drive the same
    // invocation until the actual first clock sample owns the real fence.
    tokio::time::timeout(
        Duration::from_secs(5),
        std::future::poll_fn(|context| match invocation.as_mut().poll(context) {
            Poll::Ready(report) => panic!("clock must wait before its second sample: {report:?}"),
            Poll::Pending if held.lock().unwrap().is_some() => Poll::Ready(()),
            Poll::Pending => Poll::Pending,
        }),
    )
    .await
    .expect("bounded actual clock fence observation");
}

#[tokio::test]
async fn actual_clock_waits_on_original_grant_and_samples_each_import_once() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_after_first_sample();
    let (request, control) = f.request("real-clock-contention");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_fence(invocation.as_mut(), &held).await;
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
    pending_at_fence(invocation.as_mut(), &held).await;
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
    pending_at_fence(invocation.as_mut(), &held).await;
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
    pending_at_fence(invocation.as_mut(), &held).await;
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

#[tokio::test]
async fn real_session_currentness_wait_precedes_store_registration_and_calls_guest_once() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_before_session();
    let (request, control) = f.request("real-session-contention");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_fence(invocation.as_mut(), &held).await;
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    assert_eq!(f.broker.snapshot().sessions, 0);
    assert_eq!(f.backend.resource_snapshot().live_stores, 0);
    assert_eq!(f.backend.active_instance_reservations(), 1);
    held.lock().unwrap().take().unwrap().release();
    let report = invocation.await;
    let GuestOutcome::Returned { consumption, .. } = report.outcome.unwrap() else {
        panic!("one original guest must complete after session contention");
    };
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 2);
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(control
        .budget
        .finalize_at(Some(&consumption), Instant::now())
        .violation()
        .is_none());
    f.idle();
}

#[tokio::test]
async fn dropping_real_session_currentness_wait_retires_prepared_owner_without_guest() {
    let signed = signed::Fixture::new(true).await;
    let f = &signed.guest;
    let held = signed.hold_before_session();
    let (request, control) = f.request("real-session-drop");
    let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
    pending_at_fence(invocation.as_mut(), &held).await;
    assert_eq!(f.broker.snapshot().sessions, 0);
    assert_eq!(f.backend.resource_snapshot().live_stores, 0);
    drop(invocation);
    held.lock().unwrap().take().unwrap().release();
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    f.idle();
}

#[tokio::test]
async fn real_session_wait_keeps_original_cancellation_and_lease_expiry() {
    for cancelled in [false, true] {
        let signed = signed::Fixture::new(true).await;
        let f = &signed.guest;
        let held = signed.hold_before_session();
        let (request, control) = f.request("real-session-stop");
        let mut invocation = Box::pin(f.backend.invoke_contained(request, &control));
        pending_at_fence(invocation.as_mut(), &held).await;
        if cancelled {
            control.probe.0.store(true, Ordering::Release);
        } else {
            signed.expire_original_lease();
        }
        held.lock().unwrap().take().unwrap().release();
        let report = invocation.await;
        if cancelled {
            assert!(matches!(
                report.outcome.unwrap(),
                GuestOutcome::Interrupted { .. }
            ));
        } else {
            let error = report.outcome.unwrap_err();
            assert_eq!(error.code, latent_core::PlatformErrorCode::Unavailable);
            assert!(error.details.iter().any(|detail| detail
                .fields
                .get("reason")
                .map(String::as_str)
                == Some("admission-clock-lease-uncovered")));
        }
        assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
    }
}

#[tokio::test]
async fn legacy_session_without_timer_fails_closed_before_store_or_guest() {
    let signed = signed::Fixture::new(false).await;
    let f = &signed.guest;
    let held = signed.hold_before_session();
    let (request, control) = f.request("real-session-legacy");
    let report = f.backend.invoke_contained(request, &control).await;
    held.lock().unwrap().take().unwrap().release();
    assert_eq!(
        report.outcome.unwrap_err().code,
        latent_core::PlatformErrorCode::Unavailable
    );
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
}

#[tokio::test]
#[ignore = "requires explicitly rebuilt std clock guest from the pinned infrastructure source"]
async fn ordinary_std_systemtime_runs_on_signed_current_grants_and_fresh_stores() {
    ordinary_clock(false).await;
}

#[tokio::test]
#[ignore = "requires explicitly rebuilt std clock guest and controlled native-stack profile"]
async fn ordinary_std_systemtime_with_owned_native_stack() {
    ordinary_clock(true).await;
}

async fn ordinary_clock(owned_native_stacks: bool) {
    use sha2::{Digest, Sha256};
    let directory = std::path::PathBuf::from(
        std::env::var_os("LSF_RUST_STD_CLOCK_GUEST")
            .expect("prepare the ordinary std clock component"),
    );
    let marker: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("clock-guest.json")).unwrap())
            .unwrap();
    assert_eq!(marker["profile"], "lsf-rust-std-clock-built-source-v1");
    assert_eq!(marker["compiler"], "1.97.1");
    assert_eq!(marker["target"], "wasm32-unknown-unknown");
    assert_eq!(marker["applicationClockSdkCalled"], false);
    let bytes = std::fs::read(directory.join("component.wasm")).unwrap();
    assert!(!bytes.is_empty() && bytes.len() < 4 * 1024 * 1024);
    assert_eq!(
        marker["componentDigest"],
        format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&bytes))
        )
    );
    // Cryptographic test publisher/builder admission and actual production
    // broker execution. The separate build marker is an input witness, not
    // proof of production builder trust or std/thread runtime qualification.
    let signed = signed::Fixture::with_component_profile(true, &bytes, owned_native_stacks).await;
    let f = &signed.guest;
    for id in ["ordinary-clock-first", "ordinary-clock-fresh"] {
        let (request, control) = f.request(id);
        let report = f.backend.invoke_contained(request, &control).await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("ordinary std::time::SystemTime must return through the current clock host");
        };
        let values: serde_json::Value = serde_json::from_slice(&output).unwrap();
        assert!(values[0].as_str().unwrap().parse::<u64>().unwrap() > 0);
        assert!(control
            .budget
            .finalize_at(Some(&consumption), Instant::now())
            .violation()
            .is_none());
        f.idle();
        println!(
            "{}",
            serde_json::json!({"schemaVersion":"latent.rust.std-clock-execution.v1",
            "activation":id,"clockKind":marker["clockKind"],"componentDigest":marker["componentDigest"],
            "fuel":consumption.cpu_fuel,"peakWasmBytes":consumption.peak_memory_bytes,
            "wallMicros":consumption.wall_time_micros,"sampledPhysicalOwnersRetired":true,
            "ownedNativeStacks":owned_native_stacks})
        );
    }
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 4);
    assert_eq!(f.backend.resource_snapshot().stores_created, 2);
    fixture::revoke(&f.policies);
    let (request, control) = f.request("ordinary-clock-denied");
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 4);
    f.idle();
}
