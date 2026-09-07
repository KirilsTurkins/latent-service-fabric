use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationClock, ClockSample};
use latent_executor::GuestOutcome;
use latent_wasmtime::{CapturedLog, LogSinkError, StructuredLogSink};
use serde_json::json;

use super::support::*;

struct ClockStepSink {
    clock: Arc<ManualClock>,
    origin: ClockSample,
    accepted: AtomicUsize,
}

impl StructuredLogSink for ClockStepSink {
    fn try_emit(&self, record: &CapturedLog, _encoded: &[u8]) -> Result<(), LogSinkError> {
        assert_eq!(record.message, "clock-step");
        let index = self.accepted.fetch_add(1, Ordering::AcqRel);
        let (wall, nanos) = if index == 0 { (9_000, 40) } else { (8_000, 20) };
        self.clock.set(ClockSample::new(
            wall,
            self.origin.monotonic() + Duration::from_nanos(nanos),
        ));
        Ok(())
    }
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn wall_adjustments_are_visible_monotonic_regressions_clamp_and_new_invocations_reset() {
    let clock = Arc::new(ManualClock::new());
    let origin = clock.sample();
    let sink = Arc::new(ClockStepSink {
        clock: clock.clone(),
        origin,
        accepted: AtomicUsize::new(0),
    });
    let mut services = services(&clock);
    services.log_sink = Some(sink.clone());
    let (backend, prepared) = prepared(config(), services).await;
    let cancellation = Cancellation::new("clock-first", &budget(), origin);
    let invocation = request(&prepared, &cancellation, "clocks", &json!([]));
    let outcome = run(&backend, invocation, &cancellation).await;
    assert!(
        matches!(&outcome, GuestOutcome::Returned { consumption, .. }
        if consumption.wall_time_micros == 0),
        "terminal consumption uses the injected sub-microsecond monotonic interval"
    );
    let output = returned(outcome);
    assert_eq!(
        output,
        json!([[
            {"monotonic": "0", "wall": "10000"},
            {"monotonic": "40", "wall": "9000"},
            {"monotonic": "40", "wall": "8000"}
        ]])
    );
    assert_eq!(sink.accepted.load(Ordering::Acquire), 2);

    // The same cell gets fresh clamp state within the factory's clock domain.
    let cancellation = Cancellation::new("clock-second", &budget(), clock.sample());
    let invocation = request(&prepared, &cancellation, "clocks", &json!([]));
    let output = returned(run(&backend, invocation, &cancellation).await);
    assert_eq!(output[0][0], json!({"monotonic": "20", "wall": "8000"}));
    assert_eq!(backend.resource_snapshot().stores_created, 2);
}
