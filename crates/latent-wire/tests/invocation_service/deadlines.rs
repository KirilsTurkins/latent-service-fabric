use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationClock, ClockSample};
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

struct CrossWallBoundary(Arc<Clock>);

impl ActivationObserver for CrossWallBoundary {
    fn on_observation(
        &self,
        _context: &ActivationObservationContext,
        event: &ActivationObservation,
    ) {
        if matches!(&event.kind, ActivationObservationKind::Received) {
            let sample = self.0.sample();
            self.0.set(ClockSample::new(
                sample.unix_millis() + 1,
                sample.monotonic() + Duration::from_micros(200),
            ));
        }
    }
}

#[tokio::test(start_paused = true)]
async fn submillisecond_transport_precision_reaches_the_shared_execution_ledger() {
    let clock = Arc::new(Clock::default());
    // The scheduler reads Tokio's clock. Anchor the injected clock to the same
    // paused origin so host scheduling cannot spend this precision-test budget.
    clock.set(ClockSample::new(
        clock.sample().unix_millis(),
        tokio::time::Instant::now().into_std(),
    ));
    let arrival = clock.sample();
    let observer = Arc::new(CrossWallBoundary(Arc::clone(&clock)));
    let harness = Harness::with_observer(clock, observer);
    let adapter = harness.adapter();
    let mut input = authenticated(request("precise-wire-deadline"));
    input.set_timeout(Duration::from_micros(1800));
    let response = finish(adapter.invoke(input)).await.unwrap().into_inner();
    assert!(
        matches!(
            response.result,
            Some(latent_wire::invocation::proto::invoke_response::Result::Success(_))
        ),
        "precision fixture must succeed: {:?}",
        response.result
    );
    assert_eq!(
        *harness.backend.deadlines.lock().unwrap(),
        vec![Some(arrival.monotonic() + Duration::from_micros(1800))],
    );
    let terminal = status(&adapter, "precise-wire-deadline").await;
    assert_eq!(terminal.terminal_state.as_deref(), Some("completed"));
    assert_eq!(terminal.final_consumption.unwrap().cpu_fuel, 3);
    harness.assert_idle();
}
