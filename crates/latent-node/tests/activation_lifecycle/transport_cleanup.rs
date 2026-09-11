use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationClock, ActivationId, ActivationPhase, ActivationTerminalState, CancelDisposition,
    ClockSample, IncomingDeadline,
};
use latent_node::ActivationTransportInterruption as Cause;
use latent_scheduler::CellClass;
use latent_telemetry::{
    ActivationCleanupDisposition, ActivationObservation, ActivationObservationContext,
    ActivationObservationKind, ActivationObserver,
};

use super::model::request;
use super::support::{finish, pending, tenant, Harness};

#[derive(Default)]
pub struct Observations {
    pub accepted_cancel: AtomicUsize,
    pub released: AtomicUsize,
    pub failed: AtomicUsize,
    pub quarantined: AtomicUsize,
    pub terminal: AtomicUsize,
}
impl ActivationObserver for Observations {
    fn on_observation(&self, _: &ActivationObservationContext, event: &ActivationObservation) {
        let counter = match &event.kind {
            ActivationObservationKind::Cancellation(CancelDisposition::Accepted) => {
                &self.accepted_cancel
            }
            ActivationObservationKind::Cleanup(ActivationCleanupDisposition::Released) => {
                &self.released
            }
            ActivationObservationKind::Cleanup(
                ActivationCleanupDisposition::Failed | ActivationCleanupDisposition::Abandoned,
            ) => &self.failed,
            ActivationObservationKind::Cleanup(ActivationCleanupDisposition::Quarantined) => {
                &self.quarantined
            }
            ActivationObservationKind::Terminal(_) => &self.terminal,
            _ => return,
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }
}

#[tokio::test]
async fn acknowledged_disconnects_reuse_the_same_capacity_without_explicit_cancel_events() {
    let observations = Arc::new(Observations::default());
    let harness = Harness::with_observer(1, 8, Some(observations.clone()));
    for index in 0..3 {
        let id = format!("disconnect-{index}");
        harness.backend.gate.close();
        let mut owner = harness.manager.start(request(&id)).unwrap();
        pending(Pin::new(&mut owner)).await;
        let pin = harness
            .backend
            .requests
            .lock()
            .unwrap()
            .last()
            .unwrap()
            .activation
            .resolved_revision
            .clone();
        let deadline = *harness.backend.deadlines.lock().unwrap().last().unwrap();
        let probe = harness
            .backend
            .probes
            .lock()
            .unwrap()
            .last()
            .unwrap()
            .clone();
        assert!(!probe.upgrade().unwrap().is_cancelled());
        let mut owner = owner.interrupt_for_cleanup(Cause::Disconnected);
        assert!(probe.upgrade().unwrap().is_cancelled());
        pending(Pin::new(&mut owner)).await;
        assert_eq!(harness.status(&id).phase, ActivationPhase::Running);
        assert_eq!(harness.status(&id).terminal_state, None);
        assert_eq!(harness.manager.journal().snapshot().active, 1);
        assert_eq!(
            harness
                .quotas
                .snapshot_now(&tenant())
                .unwrap()
                .active_activations,
            1
        );
        assert_eq!(
            harness
                .scheduler
                .observations(CellClass::Tiny)
                .active_leases,
            1
        );
        assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 1);
        assert_eq!(harness.backend.live_prepared.load(Ordering::Relaxed), 1);
        assert_eq!(observations.accepted_cancel.load(Ordering::Relaxed), 0);
        harness.backend.gate.open();
        // The fixture returns Success even after stop, with affirmative cleanup.
        // Publication must retain the raw interruption while reusing the cell.
        let receipt = finish(owner).await;
        assert!(matches!(
            receipt.outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Cancelled,
                ..
            }
        ));
        assert_eq!(receipt.resolved_revision, pin);
        assert_eq!(
            *harness.backend.deadlines.lock().unwrap().last().unwrap(),
            deadline
        );
        let consumption = harness.status(&id).final_consumption.unwrap();
        assert_eq!(
            (
                consumption.cpu_fuel,
                consumption.log_bytes,
                consumption.peak_memory_bytes
            ),
            (3, 4, 8)
        );
        assert!(probe.upgrade().is_none());
        harness.assert_idle();
        let pool = harness.scheduler.observations(CellClass::Tiny);
        assert_eq!((pool.available, pool.quarantined), (1, 0));
        assert_eq!(observations.released.load(Ordering::Relaxed), index + 1);
        assert_eq!(observations.terminal.load(Ordering::Relaxed), index + 1);
    }
    assert_eq!(observations.accepted_cancel.load(Ordering::Relaxed), 0);
    assert!(matches!(
        finish(harness.manager.start(request("healthy")).unwrap())
            .await
            .outcome,
        ActivationOutcome::Succeeded(_)
    ));
    harness.assert_idle();
}

#[tokio::test]
async fn unpolled_and_preparation_stops_do_not_start_or_reconstruct_work() {
    for stage in 0..3 {
        let harness = Harness::standard();
        match stage {
            1 => harness.artifacts.gate.close(),
            2 => harness.backend.prepare_gate.close(),
            _ => {}
        }
        let mut owner = harness.manager.start(request("before-cell")).unwrap();
        if stage != 0 {
            pending(Pin::new(&mut owner)).await;
        }
        let owner = owner.interrupt_for_cleanup(Cause::Disconnected);
        let receipt = finish(owner).await;
        assert!(matches!(
            receipt.outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Cancelled,
                ..
            }
        ));
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
        if stage == 0 {
            assert!(harness.catalog.keys.lock().unwrap().is_empty());
            assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
        }
        assert_eq!(harness.manager.journal().snapshot().completed, 1);
        assert_eq!(harness.scheduler.observations(CellClass::Tiny).available, 1);
        harness.assert_idle();
    }
}

#[tokio::test]
async fn queued_disconnect_reclaims_only_its_exact_reservation() {
    let harness = Harness::standard();
    harness.backend.gate.close();
    let mut running = harness.manager.start(request("running")).unwrap();
    pending(Pin::new(&mut running)).await;
    let mut queued = harness.manager.start(request("queued")).unwrap();
    pending(Pin::new(&mut queued)).await;
    assert_eq!(
        harness.scheduler.observations(CellClass::Tiny).queue_depth,
        1
    );
    finish(queued.interrupt_for_cleanup(Cause::Disconnected)).await;
    let pool = harness.scheduler.observations(CellClass::Tiny);
    assert_eq!(
        (pool.queue_depth, pool.active_leases, pool.quarantined),
        (0, 1, 0)
    );
    assert_eq!(
        harness.status("queued").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(harness.status("running").terminal_state, None);
    assert_eq!(
        harness
            .quotas
            .snapshot_now(&tenant())
            .unwrap()
            .active_activations,
        1
    );
    harness.backend.gate.open();
    finish(running).await;
    harness.assert_idle();
}

#[tokio::test(start_paused = true)]
async fn exact_expiry_and_explicit_cancel_keep_priority_over_transport_and_success() {
    for explicit in [false, true] {
        for expired in [false, true] {
            for cause in [Cause::Disconnected, Cause::DeadlineExceeded] {
                let harness = Harness::standard();
                let arrival = harness.clock.sample();
                // The paused scheduler stays no later than this fixture sample;
                // preserve that same sample used by the load/admission fixture.
                let origin = arrival.monotonic();
                let expiry = origin + Duration::from_millis(20);
                harness.backend.gate.close();
                let mut owner = harness
                    .manager
                    .start_with_deadline(
                        request("priority"),
                        Some(IncomingDeadline::new(expiry, arrival.unix_millis() + 20)),
                    )
                    .unwrap();
                pending(Pin::new(&mut owner)).await;
                let owner = owner.interrupt_for_cleanup(cause);
                if explicit {
                    assert_eq!(
                        harness
                            .manager
                            .cancel_for(&tenant(), &ActivationId("priority".into()), "explicit")
                            .unwrap(),
                        CancelDisposition::Accepted
                    );
                }
                if expired {
                    harness
                        .clock
                        .set(ClockSample::new(arrival.unix_millis() + 90_000, expiry));
                }
                harness.backend.gate.open();
                finish(owner).await;
                assert_eq!(
                    harness.status("priority").terminal_state,
                    Some(if explicit {
                        ActivationTerminalState::Cancelled
                    } else if expired || cause == Cause::DeadlineExceeded {
                        ActivationTerminalState::DeadlineExceeded
                    } else {
                        ActivationTerminalState::Cancelled
                    })
                );
                assert_eq!(
                    *harness.backend.deadlines.lock().unwrap(),
                    vec![Some(expiry)]
                );
                assert_eq!(harness.scheduler.observations(CellClass::Tiny).available, 1);
                harness.assert_idle();
            }
        }
    }
}

#[tokio::test]
async fn marking_an_already_completed_handle_cannot_stop_its_reused_id() {
    let harness = Harness::new(1, 1);
    let mut old = harness.manager.start(request("reused")).unwrap();
    finish(&mut old).await;
    finish(harness.manager.start(request("evict")).unwrap()).await;
    let replacement = harness.manager.start(request("reused")).unwrap();
    drop(old.interrupt_for_cleanup(Cause::Disconnected));
    assert_eq!(harness.status("reused").terminal_state, None);
    assert!(matches!(
        finish(replacement).await.outcome,
        ActivationOutcome::Succeeded(_)
    ));
    harness.assert_idle();
}
