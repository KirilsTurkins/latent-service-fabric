#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/telemetry", "examples/guest_metrics"],
    world: "tests:metrics/service@1.0.0",
    with: { "latent:telemetry/custom@0.1.0": latent_guest::bindings::metrics },
});

struct Capsule;
impl exports::tests::metrics::api::Guest for Capsule {
    fn run(which: u32, text: String, handle: u64) -> u64 {
        probe(which, text, handle)
    }
}
export!(Capsule);

use latent_guest::metrics::{self, Metric, MetricKind, TelemetryError};
fn probe(which: u32, text: String, _handle: u64) -> u64 {
    let kind = match which {
        0 => MetricKind::Counter,
        1 => MetricKind::UpDownCounter,
        2 => MetricKind::Gauge,
        _ => MetricKind::Histogram,
    };
    match metrics::emit_metric(&Metric {
        name: text,
        kind,
        value: 2.0,
        unit: "1".into(),
        attributes: vec![("region".into(), "east".into())],
    }) {
        Ok(true) => 1,
        Ok(false) => 0,
        Err(TelemetryError::InvalidName) => 10,
        Err(TelemetryError::BudgetExhausted) => 11,
        Err(TelemetryError::Unavailable) => 12,
    }
}
