use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationClock, ActivationId, ActivationPhase, ActivationTerminalState, IncomingDeadline,
    PlatformErrorCode, RouteGeneration,
};

use super::model::request;
use super::support::{error, finish, pending, tenant, Harness};

fn busy(harness: &Harness, policy: bool, attempts: Arc<AtomicUsize>) {
    let hook = Arc::new(move || {
        attempts.fetch_add(1, Ordering::Relaxed);
        Err(error(
            PlatformErrorCode::Unavailable,
            "admission-authority-busy",
        ))
    });
    if policy {
        *harness.catalog.policy_hook.lock().unwrap() = Some(hook);
    } else {
        *harness.catalog.resolve_hook.lock().unwrap() = Some(hook);
    }
}

#[tokio::test(start_paused = true)]
async fn authority_wait_preserves_one_catalog_and_admits_exactly_once() {
    for policy in [false, true] {
        let harness = Harness::standard();
        let attempts = Arc::new(AtomicUsize::new(0));
        busy(&harness, policy, attempts.clone());
        let mut handle = harness.manager.start(request("lease-renewal")).unwrap();
        pending(Pin::new(&mut handle)).await;
        assert_eq!(attempts.load(Ordering::Relaxed), 1);
        assert_eq!(
            harness.status("lease-renewal").phase,
            if policy {
                ActivationPhase::Resolved
            } else {
                ActivationPhase::Received
            }
        );
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
        assert_eq!(
            harness
                .quotas
                .snapshot_now(&tenant())
                .unwrap()
                .active_activations,
            0
        );
        harness.catalog.generation.store(2, Ordering::Release);
        *harness.catalog.resolve_hook.lock().unwrap() = None;
        *harness.catalog.policy_hook.lock().unwrap() = None;
        tokio::time::advance(Duration::from_millis(10)).await;
        let receipt = finish(handle).await;
        assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
        assert_eq!(
            receipt.resolved_revision.unwrap().route_generation,
            RouteGeneration(1)
        );
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 1);
        let events = harness
            .manager
            .events(&tenant(), &ActivationId("lease-renewal".into()))
            .unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|event| event.phase == ActivationPhase::Resolved)
                .count(),
            1
        );
        assert_eq!(
            events
                .iter()
                .filter(|event| event.phase == ActivationPhase::Admitted)
                .count(),
            1
        );
        harness.assert_idle();
    }
}

#[tokio::test(start_paused = true)]
async fn unavailable_poisoned_revoked_and_uncovered_authority_are_not_retried() {
    for (code, message) in [
        (
            PlatformErrorCode::Unavailable,
            "admission-authority-poisoned",
        ),
        (
            PlatformErrorCode::Unavailable,
            "admission-clock-lease-uncovered",
        ),
        (PlatformErrorCode::Unavailable, "binding-publication-busy"),
        (
            PlatformErrorCode::PermissionDenied,
            "admission-authority-busy",
        ),
    ] {
        for policy in [false, true] {
            let harness = Harness::standard();
            let attempts = Arc::new(AtomicUsize::new(0));
            let observed = attempts.clone();
            let hook = Arc::new(move || {
                observed.fetch_add(1, Ordering::Relaxed);
                Err(error(code, message))
            });
            if policy {
                *harness.catalog.policy_hook.lock().unwrap() = Some(hook);
            } else {
                *harness.catalog.resolve_hook.lock().unwrap() = Some(hook);
            }
            let receipt = finish(harness.manager.start(request("fail-closed")).unwrap()).await;
            let ActivationOutcome::Failed { error: failure, .. } = receipt.outcome else {
                panic!("failed outcome")
            };
            assert_eq!(
                failure.code,
                if policy && code != PlatformErrorCode::Unavailable {
                    PlatformErrorCode::AdmissionRejected
                } else {
                    code
                }
            );
            assert_eq!(attempts.load(Ordering::Relaxed), 1);
            assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
            harness.assert_idle();
        }
    }
}

#[tokio::test(start_paused = true)]
async fn expiry_and_cancellation_stop_pre_admission_wait_without_dispatch() {
    for policy in [false, true] {
        for cancellation in [false, true] {
            let harness = Harness::standard();
            let sample = harness.clock.sample();
            let deadline = IncomingDeadline::new(
                sample.monotonic() + Duration::from_millis(15),
                sample.unix_millis() + 15,
            );
            let attempts = Arc::new(AtomicUsize::new(0));
            busy(&harness, policy, attempts.clone());
            let mut handle = harness
                .manager
                .start_with_deadline(request("interrupted"), Some(deadline))
                .unwrap();
            pending(Pin::new(&mut handle)).await;
            if cancellation {
                harness
                    .manager
                    .cancel_for(&tenant(), &ActivationId("interrupted".into()), "stop")
                    .unwrap();
            } else {
                harness.clock.advance(Duration::from_millis(15));
            }
            let receipt = finish(handle).await;
            let ActivationOutcome::Failed { error: failure, .. } = receipt.outcome else {
                panic!("failed outcome")
            };
            assert_eq!(
                failure.code,
                if cancellation {
                    PlatformErrorCode::Cancelled
                } else {
                    PlatformErrorCode::DeadlineExceeded
                }
            );
            assert_eq!(attempts.load(Ordering::Relaxed), 1);
            assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
            harness.assert_idle();
        }
    }
}

#[tokio::test(start_paused = true)]
async fn busy_authority_wait_has_a_shared_finite_ceiling_and_no_background_owner() {
    let harness = Harness::standard();
    let attempts = Arc::new(AtomicUsize::new(0));
    busy(&harness, false, attempts.clone());
    let mut handle = harness.manager.start(request("finite-wait")).unwrap();
    pending(Pin::new(&mut handle)).await;
    tokio::time::advance(Duration::from_secs(5)).await;
    let receipt = finish(handle).await;
    let ActivationOutcome::Failed { error: failure, .. } = receipt.outcome else {
        panic!("failed outcome")
    };
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(attempts.load(Ordering::Relaxed), 1);
    harness.assert_idle();

    let mut handle = harness.manager.start(request("abandoned-wait")).unwrap();
    pending(Pin::new(&mut handle)).await;
    drop(handle);
    tokio::time::advance(Duration::from_secs(10)).await;
    assert_eq!(attempts.load(Ordering::Relaxed), 2);
    assert_eq!(
        harness.status("abandoned-wait").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}
