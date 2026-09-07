use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use latent_core::ActivationClock;
use latent_telemetry::{
    ActivationObservation, ActivationObservationContext, ActivationObservationKind,
    ActivationObserver,
};
use latent_wire::invocation::InvocationService;
use tonic::Code;

use super::support::{authenticated, finish, request, status, Clock, Harness};

struct AdvanceOnReceived(Arc<Clock>);

impl ActivationObserver for AdvanceOnReceived {
    fn on_observation(
        &self,
        _context: &ActivationObservationContext,
        event: &ActivationObservation,
    ) {
        if matches!(&event.kind, ActivationObservationKind::Received) {
            self.0.advance(Duration::from_millis(2));
        }
    }
}

#[tokio::test]
async fn deadline_expiring_during_acceptance_aborts_before_first_lifecycle_poll() {
    let clock = Arc::new(Clock::default());
    let observer = Arc::new(AdvanceOnReceived(Arc::clone(&clock)));
    let harness = Harness::with_observer(Arc::clone(&clock), observer);
    let adapter = harness.adapter();
    let mut input = request("expired-during-received");
    input.deadline_unix_millis = Some(clock.sample().unix_millis() + 1);

    let error = finish(adapter.invoke(authenticated(input)))
        .await
        .expect_err("deadline expired while accepting exact owner");
    assert_eq!(error.code(), Code::DeadlineExceeded);
    let terminal = status(&adapter, "expired-during-received").await;
    assert_eq!(terminal.phase, "received");
    assert_eq!(
        terminal.terminal_state.as_deref(),
        Some("deadline_exceeded")
    );
    assert_eq!(
        terminal
            .final_consumption
            .expect("final accounting")
            .cpu_fuel,
        0
    );
    assert_eq!(harness.manager.journal().snapshot().begun, 1);
    assert_eq!(harness.manager.journal().snapshot().completed, 1);
    assert_eq!(harness.catalog.pins.load(Ordering::Relaxed), 0);
    assert!(harness
        .catalog
        .keys
        .lock()
        .expect("no resolution")
        .is_empty());
    assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 0);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}
