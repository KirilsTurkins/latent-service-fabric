use super::model::request;
use super::support::{finish, pending, tenant, Harness};
use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, ActivationPhase, ActivationTerminalState, CancelDisposition};
use latent_scheduler::CellClass;
use std::pin::Pin;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn transport_expiry_before_first_poll_has_deadline_status_without_admission() {
    let harness = Harness::standard();
    let handle = harness.manager.start(request("unpolled-expiry")).unwrap();
    assert_eq!(
        harness.status("unpolled-expiry").phase,
        ActivationPhase::Received
    );
    handle.abort_due_to_deadline();
    let status = harness.status("unpolled-expiry");
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::DeadlineExceeded)
    );
    assert_eq!(status.final_consumption.unwrap().cpu_fuel, 0);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    harness.assert_idle();
    // Plain abandonment retains its distinct meaning.
    drop(harness.manager.start(request("disconnect")).unwrap());
    assert_eq!(
        harness.status("disconnect").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    harness.assert_idle();
}

#[tokio::test]
async fn queued_transport_expiry_reclaims_only_its_owned_waiter() {
    let harness = Harness::standard();
    harness.backend.gate.close();
    let mut running = harness.manager.start(request("running")).unwrap();
    pending(Pin::new(&mut running)).await;
    let mut queued = harness.manager.start(request("queued-expiry")).unwrap();
    pending(Pin::new(&mut queued)).await;
    assert_eq!(
        harness.status("queued-expiry").phase,
        ActivationPhase::Queued
    );
    queued.abort_due_to_deadline();
    assert_eq!(
        harness.status("queued-expiry").terminal_state,
        Some(ActivationTerminalState::DeadlineExceeded)
    );
    let pool = harness.scheduler.observations(CellClass::Tiny);
    assert_eq!(pool.queue_depth, 0);
    assert_eq!(pool.active_leases, 1);
    assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 1);
    harness.backend.gate.open();
    assert!(matches!(
        finish(running).await.outcome,
        ActivationOutcome::Succeeded(_)
    ));
    harness.assert_idle();
}

#[tokio::test]
async fn expiry_during_fetch_preparation_and_execution_finalizes_the_original_accounting() {
    for stage in 0..3 {
        let harness = Harness::standard();
        match stage {
            0 => harness.artifacts.gate.close(),
            1 => harness.backend.prepare_gate.close(),
            _ => harness.backend.gate.close(),
        }
        let mut handle = harness.manager.start(request("active-expiry")).unwrap();
        pending(Pin::new(&mut handle)).await;
        assert_eq!(
            harness.status("active-expiry").phase,
            if stage == 2 {
                ActivationPhase::Running
            } else {
                ActivationPhase::Materializing
            }
        );
        handle.abort_due_to_deadline();
        let status = harness.status("active-expiry");
        assert_eq!(
            status.terminal_state,
            Some(ActivationTerminalState::DeadlineExceeded)
        );
        let consumption = status.final_consumption.unwrap();
        assert_eq!(consumption.cpu_fuel, if stage == 2 { 3 } else { 0 });
        assert_eq!(consumption.log_bytes, if stage == 2 { 4 } else { 0 });
        assert_eq!(
            consumption.peak_memory_bytes,
            if stage == 2 { 8 } else { 0 }
        );
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            u32::from(stage == 2)
        );
        harness.assert_idle();
    }
}

#[tokio::test]
async fn accepted_explicit_cancellation_preserves_its_terminal_winner_on_deadline_abort() {
    let harness = Harness::standard();
    harness.backend.gate.close();
    let mut handle = harness.manager.start(request("cancel-winner")).unwrap();
    pending(Pin::new(&mut handle)).await;
    assert_eq!(
        harness
            .manager
            .cancel_for(
                &tenant(),
                &ActivationId("cancel-winner".into()),
                "caller cancelled"
            )
            .unwrap(),
        CancelDisposition::Accepted
    );
    handle.abort_due_to_deadline();
    assert_eq!(
        harness.status("cancel-winner").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(
        harness
            .status("cancel-winner")
            .final_consumption
            .unwrap()
            .cpu_fuel,
        3
    );
    harness.assert_idle();
}

#[tokio::test]
async fn aborting_completed_handle_cannot_change_terminal_status_or_a_reused_identity() {
    let harness = Harness::new(1, 1);
    let mut old = harness.manager.start(request("reused")).unwrap();
    let receipt = finish(&mut old).await;
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    assert_eq!(
        harness.status("reused").terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    // Evict the old terminal entry, then accept the same caller ID again.
    finish(harness.manager.start(request("evict-old")).unwrap()).await;
    let replacement = harness.manager.start(request("reused")).unwrap();
    assert_eq!(harness.status("reused").phase, ActivationPhase::Received);
    old.abort_due_to_deadline();
    assert_eq!(harness.status("reused").terminal_state, None);
    assert_eq!(
        harness.manager.cancellation_snapshot().active_registrations,
        1
    );
    drop(replacement);
    assert_eq!(
        harness.status("reused").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    harness.assert_idle();
}
