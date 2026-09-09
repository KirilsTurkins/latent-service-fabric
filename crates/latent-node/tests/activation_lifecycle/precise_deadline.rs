use std::pin::Pin;
use std::sync::atomic::Ordering;
use std::time::Duration;

use latent_activation::ActivationOutcome;
use latent_core::{ActivationClock, ActivationTerminalState, ClockSample, IncomingDeadline};

use super::model::request;
use super::support::{finish, pending, Harness};

#[tokio::test(start_paused = true)]
async fn exact_ingress_expiry_survives_wall_boundary_and_clock_moves() {
    for wall_delta in [-10_000_i64, 0, 1, 10_000] {
        let harness = Harness::standard();
        let arrival = harness.clock.sample();
        let expiry = arrival.monotonic() + Duration::from_micros(1800);
        let mut input = request("precise-ingress");
        input.deadline_unix_millis = Some(arrival.unix_millis() + 2);
        let handle = harness
            .manager
            .start_with_deadline(
                input,
                Some(IncomingDeadline::new(expiry, arrival.unix_millis() + 2)),
            )
            .unwrap();
        // The old integer round trip shrank this positive 1.6 ms remainder to
        // a rejected 1 ms when the wall clock crossed one millisecond.
        harness.clock.set(ClockSample::new(
            arrival
                .unix_millis()
                .checked_add_signed(wall_delta)
                .unwrap(),
            arrival.monotonic() + Duration::from_micros(200),
        ));
        assert!(matches!(
            finish(handle).await.outcome,
            ActivationOutcome::Succeeded(_)
        ));
        assert_eq!(
            *harness.backend.deadlines.lock().unwrap(),
            vec![Some(expiry)]
        );
        harness.assert_idle();
    }
}

#[tokio::test(start_paused = true)]
async fn incoming_expiry_before_first_poll_never_resolves_or_prepares() {
    let harness = Harness::standard();
    let arrival = harness.clock.sample();
    let expiry = arrival.monotonic() + Duration::from_millis(2);
    let handle = harness
        .manager
        .start_with_deadline(
            request("expired-unpolled"),
            Some(IncomingDeadline::new(expiry, arrival.unix_millis() + 2)),
        )
        .unwrap();
    harness
        .clock
        .set(ClockSample::new(arrival.unix_millis() + 2, expiry));
    let _ = finish(handle).await;
    let status = harness.status("expired-unpolled");
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::DeadlineExceeded)
    );
    assert_eq!(status.final_consumption.unwrap().cpu_fuel, 0);
    assert_eq!(harness.backend.preparation_calls.load(Ordering::Relaxed), 0);
    assert!(harness.catalog.keys.lock().unwrap().is_empty());
    assert!(harness.backend.deadlines.lock().unwrap().is_empty());
    harness.assert_idle();
}

#[tokio::test(start_paused = true)]
async fn terminal_decision_enforces_exact_expiry_without_a_timer_wakeup() {
    for offset in [-1_i64, 0, 1] {
        let harness = Harness::standard();
        harness.backend.gate.close();
        let arrival = harness.clock.sample();
        let expiry = arrival.monotonic() + Duration::from_micros(2800);
        let mut handle = harness
            .manager
            .start_with_deadline(
                request("terminal-boundary"),
                Some(IncomingDeadline::new(expiry, arrival.unix_millis() + 3)),
            )
            .unwrap();
        pending(Pin::new(&mut handle)).await;
        assert_eq!(
            *harness.backend.deadlines.lock().unwrap(),
            vec![Some(expiry)]
        );
        let decision = if offset < 0 {
            expiry - Duration::from_nanos(1)
        } else {
            expiry + Duration::from_nanos(offset.unsigned_abs())
        };
        harness
            .clock
            .set(ClockSample::new(arrival.unix_millis() + 2, decision));
        harness.backend.gate.open();
        // Tokio time stays paused. The immediately ready backend may return a
        // successful result before the independent deadline Sleep is ready.
        let _ = finish(handle).await;
        let status = harness.status("terminal-boundary");
        assert_eq!(
            status.terminal_state,
            Some(if offset < 0 {
                ActivationTerminalState::Completed
            } else {
                ActivationTerminalState::DeadlineExceeded
            })
        );
        let consumption = status.final_consumption.unwrap();
        assert_eq!(
            (
                consumption.cpu_fuel,
                consumption.peak_memory_bytes,
                consumption.log_bytes
            ),
            (3, 8, 4)
        );
        harness.assert_idle();
    }
}
