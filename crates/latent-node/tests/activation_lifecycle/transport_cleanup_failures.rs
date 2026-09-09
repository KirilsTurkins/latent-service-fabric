use std::pin::Pin;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use latent_core::ActivationTerminalState;
use latent_node::ActivationTransportInterruption as Cause;
use latent_scheduler::CellClass;

use super::backend::{PANIC, QUARANTINE};
use super::model::request;
use super::support::{finish, pending, Harness};
use super::transport_cleanup::Observations;

#[tokio::test(start_paused = true)]
async fn unacknowledged_disconnect_quarantines_after_the_original_grace() {
    let observations = Arc::new(Observations::default());
    let harness = Harness::with_observer(1, 8, Some(observations.clone()));
    harness.backend.gate.close();
    let mut owner = harness.manager.start(request("no-ack")).unwrap();
    pending(Pin::new(&mut owner)).await;
    let mut owner = owner.interrupt_for_cleanup(Cause::Disconnected);
    pending(Pin::new(&mut owner)).await;
    tokio::time::advance(Duration::from_millis(60)).await;
    let mut owner = owner.interrupt_for_cleanup(Cause::DeadlineExceeded);
    pending(Pin::new(&mut owner)).await;
    assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 1);
    tokio::time::advance(Duration::from_millis(41)).await;
    finish(owner).await;
    assert_eq!(
        harness.status("no-ack").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(observations.quarantined.load(Ordering::Relaxed), 1);
    assert_eq!(observations.released.load(Ordering::Relaxed), 0);
    assert_eq!(observations.accepted_cancel.load(Ordering::Relaxed), 0);
    let pool = harness.scheduler.observations(CellClass::Tiny);
    assert_eq!((pool.available, pool.quarantined), (0, 1));
    harness.assert_idle();
}

#[tokio::test]
async fn backend_refusal_or_panic_keeps_quarantine_even_after_a_driven_disconnect() {
    for mode in [PANIC, QUARANTINE] {
        let observations = Arc::new(Observations::default());
        let harness = Harness::with_observer(1, 8, Some(observations.clone()));
        harness.backend.gate.close();
        let mut owner = harness.manager.start(request("failed-ack")).unwrap();
        pending(Pin::new(&mut owner)).await;
        let mut owner = owner.interrupt_for_cleanup(Cause::Disconnected);
        pending(Pin::new(&mut owner)).await;
        harness.backend.mode.store(mode, Ordering::Release);
        harness.backend.gate.open();
        finish(owner).await;
        assert_eq!(
            harness
                .status("failed-ack")
                .final_consumption
                .unwrap()
                .cpu_fuel,
            3
        );
        let pool = harness.scheduler.observations(CellClass::Tiny);
        assert_eq!((pool.available, pool.quarantined), (0, 1));
        assert_eq!(observations.released.load(Ordering::Relaxed), 0);
        assert_eq!(
            observations.failed.load(Ordering::Relaxed)
                + observations.quarantined.load(Ordering::Relaxed),
            1
        );
        assert_eq!(observations.accepted_cancel.load(Ordering::Relaxed), 0);
        assert_eq!(harness.manager.journal().snapshot().completed, 1);
        harness.assert_idle();
    }
}
