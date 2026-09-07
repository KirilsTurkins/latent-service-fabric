use std::sync::atomic::Ordering;

use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, ActivationPhase, ActivationTerminalState, CancelDisposition};
use latent_scheduler::CellClass;

use super::backend::{DROP_PANIC, PANIC, SUCCESS};
use super::model::request;
use super::support::{finish, pending, tenant, Harness};

#[tokio::test]
async fn queued_cancellation_reclaims_only_waiter_and_keeps_running_owner_intact() {
    let harness = Harness::standard();
    harness.backend.gate.close();
    let mut running = Box::pin(harness.manager.start(request("running")).expect("running"));
    pending(running.as_mut()).await;
    assert_eq!(harness.status("running").phase, ActivationPhase::Running);
    let mut queued = Box::pin(harness.manager.start(request("queued")).expect("queued"));
    pending(queued.as_mut()).await;
    assert_eq!(harness.status("queued").phase, ActivationPhase::Queued);
    assert_eq!(
        harness.scheduler.observations(CellClass::Tiny).queue_depth,
        1
    );
    assert_eq!(
        harness
            .manager
            .cancel_for(
                &tenant(),
                &ActivationId("queued".to_owned()),
                "queued cancel"
            )
            .expect("cancel"),
        CancelDisposition::Accepted
    );
    let receipt = finish(queued).await;
    assert!(matches!(
        receipt.outcome,
        ActivationOutcome::Failed {
            terminal_state: ActivationTerminalState::Cancelled,
            ..
        }
    ));
    let pool = harness.scheduler.observations(CellClass::Tiny);
    assert_eq!(pool.queue_depth, 0);
    assert_eq!(pool.active_leases, 1);
    assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 1);
    harness.backend.gate.open();
    let _receipt = finish(running).await;
    harness.assert_idle();
}

#[tokio::test]
async fn cancellation_during_fetch_preparation_and_execution_reaches_terminal_and_drops_owners() {
    for stage in 0..3 {
        let harness = Harness::standard();
        match stage {
            0 => harness.artifacts.gate.close(),
            1 => harness.backend.prepare_gate.close(),
            _ => harness.backend.gate.close(),
        }
        let mut handle = Box::pin(
            harness
                .manager
                .start(request("cancel-stage"))
                .expect("start"),
        );
        pending(handle.as_mut()).await;
        assert_eq!(
            harness.status("cancel-stage").phase,
            if stage == 2 {
                ActivationPhase::Running
            } else {
                ActivationPhase::Materializing
            }
        );
        assert_eq!(
            harness
                .manager
                .cancel_for(
                    &tenant(),
                    &ActivationId("cancel-stage".to_owned()),
                    "stage cancel"
                )
                .expect("cancel"),
            CancelDisposition::Accepted
        );
        let receipt = finish(handle).await;
        assert!(matches!(
            receipt.outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Cancelled,
                ..
            }
        ));
        assert_eq!(
            harness.status("cancel-stage").terminal_state,
            Some(ActivationTerminalState::Cancelled)
        );
        harness.assert_idle();
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            u32::from(stage == 2)
        );
    }
}

#[tokio::test]
async fn dropping_received_and_queued_handles_terminalizes_without_affecting_other_activations() {
    let harness = Harness::standard();
    drop(
        harness
            .manager
            .start(request("unpolled"))
            .expect("received"),
    );
    assert!(harness.status("unpolled").terminal_state.is_some());
    harness.assert_idle();

    harness.backend.gate.close();
    let mut running = Box::pin(
        harness
            .manager
            .start(request("running-drop-test"))
            .expect("running"),
    );
    pending(running.as_mut()).await;
    let mut queued = Box::pin(
        harness
            .manager
            .start(request("dropped-queued"))
            .expect("queued"),
    );
    pending(queued.as_mut()).await;
    drop(queued);
    assert!(harness.status("dropped-queued").terminal_state.is_some());
    assert_eq!(
        harness.scheduler.observations(CellClass::Tiny).queue_depth,
        0
    );
    assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 1);
    harness.backend.gate.open();
    let _receipt = finish(running).await;
    harness.assert_idle();
}

#[tokio::test]
async fn dropping_materialization_and_running_futures_reclaims_all_affine_state() {
    for stage in 0..3 {
        let harness = Harness::standard();
        match stage {
            0 => harness.artifacts.gate.close(),
            1 => harness.backend.prepare_gate.close(),
            _ => harness.backend.gate.close(),
        }
        let mut handle = Box::pin(harness.manager.start(request("drop-stage")).expect("start"));
        pending(handle.as_mut()).await;
        drop(handle);
        let status = harness.status("drop-stage");
        assert!(status.terminal_state.is_some());
        assert!(status.final_consumption.is_some());
        harness.assert_idle();
        if stage == 2 {
            assert_eq!(
                harness.scheduler.observations(CellClass::Tiny).quarantined,
                1
            );
        }
    }
}

#[tokio::test]
async fn dependency_panics_become_terminal_failures_and_do_not_corrupt_a_healthy_activation() {
    for backend_panic in [false, true] {
        let harness = Harness::new(2, 8);
        if backend_panic {
            harness.backend.mode.store(PANIC, Ordering::Release);
        } else {
            harness.artifacts.fail.store(2, Ordering::Release);
        }
        let receipt = finish(harness.manager.start(request("panic")).expect("start")).await;
        assert!(matches!(
            receipt.outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::PlatformFailed,
                ..
            }
        ));
        assert_eq!(
            harness.status("panic").terminal_state,
            Some(ActivationTerminalState::PlatformFailed)
        );
        harness.assert_idle();
        harness.backend.mode.store(SUCCESS, Ordering::Release);
        harness.artifacts.fail.store(0, Ordering::Release);
        let receipt = finish(
            harness
                .manager
                .start(request("after-panic"))
                .expect("healthy"),
        )
        .await;
        assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
        harness.assert_idle();
    }
}

#[tokio::test]
async fn backend_future_destructor_panics_cannot_escape_completion_or_handle_abandonment() {
    for abandon in [false, true] {
        let harness = Harness::new(2, 8);
        harness.backend.mode.store(DROP_PANIC, Ordering::Release);
        if abandon {
            harness.backend.gate.close();
        }
        let mut handle = Box::pin(harness.manager.start(request("drop-panic")).expect("start"));
        if abandon {
            pending(handle.as_mut()).await;
            let dropped = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(handle)));
            assert!(
                dropped.is_ok(),
                "future destructor panic must remain inside the manager"
            );
        } else {
            let receipt = finish(handle).await;
            assert!(matches!(
                receipt.outcome,
                ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::PlatformFailed,
                    ..
                }
            ));
        }
        let status = harness.status("drop-panic");
        assert!(status.terminal_state.is_some());
        assert_eq!(
            status
                .final_consumption
                .expect("final accounting")
                .log_bytes,
            4
        );
        assert_eq!(harness.manager.journal().snapshot().completed, 1);
        harness.assert_idle();
        harness.backend.mode.store(SUCCESS, Ordering::Release);
        harness.backend.gate.open();
        let healthy = finish(
            harness
                .manager
                .start(request("after-drop-panic"))
                .expect("healthy"),
        )
        .await;
        assert!(matches!(healthy.outcome, ActivationOutcome::Succeeded(_)));
        harness.assert_idle();
    }
}
