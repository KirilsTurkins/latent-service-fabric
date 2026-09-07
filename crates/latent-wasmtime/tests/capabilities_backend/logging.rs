use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use latent_core::ActivationClock;
use latent_wasmtime::{CapturedLog, LogSinkError, StructuredLogSink};
use serde_json::{json, Value};

use super::support::*;

#[derive(Default)]
struct RecordingSink {
    reject_next: AtomicBool,
    accepted: Mutex<Vec<Vec<u8>>>,
}

impl StructuredLogSink for RecordingSink {
    fn try_emit(&self, _record: &CapturedLog, encoded: &[u8]) -> Result<(), LogSinkError> {
        if self.reject_next.swap(false, Ordering::AcqRel) {
            return Err(LogSinkError::Unavailable);
        }
        self.accepted
            .lock()
            .expect("sink lock")
            .push(encoded.to_vec());
        Ok(())
    }
}

const MESSAGE: &str = "quoted \"line\"\nslash\\ café";

fn fields() -> Value {
    json!([
        {"name": "z", "value": "last\nvalue"},
        {"name": "activation_id", "value": "guest-claim"},
        {"name": "a", "value": "first\"value"}
    ])
}

fn expected_record() -> Vec<u8> {
    // An independently written wire expectation includes punctuation, escaped
    // values, trusted correlation and sorted fields, including guest data.
    concat!(
        "{\"activation_id\":\"exact-log\",\"level\":\"info\",",
        "\"message\":\"quoted \\\"line\\\"\\nslash\\\\ café\",\"fields\":{",
        "\"a\":\"first\\\"value\",\"activation_id\":\"guest-claim\",",
        "\"latent.activation_id\":\"exact-log\",",
        "\"latent.span_id\":\"span-pinned\",",
        "\"latent.trace_id\":\"trace-pinned\",\"z\":\"last\\nvalue\"}}"
    )
    .as_bytes()
    .to_vec()
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn exact_escaped_correlated_record_budget_accepts_at_boundary_only() {
    let expected = expected_record();
    let bytes = u64::try_from(expected.len()).expect("record bytes");
    let clock = Arc::new(ManualClock::new());
    let sink = Arc::new(RecordingSink::default());
    let mut services = services(&clock);
    services.log_sink = Some(sink.clone());
    let (backend, prepared) = prepared(config(), services).await;
    for grant_bytes in [bytes - 1, bytes] {
        let mut grant = budget();
        grant.log_bytes = grant_bytes;
        let cancellation = Cancellation::new("exact-log", &grant, clock.sample());
        let request = request(
            &prepared,
            &cancellation,
            "log-probe",
            &json!([MESSAGE, fields()]),
        );
        let output = returned(run(&backend, request, &cancellation).await);
        assert_eq!(unsigned(&output[0]["before"]), grant_bytes);
        let consumed = if grant_bytes == bytes {
            assert_eq!(output[0]["outcome"], json!({"ok": true}));
            assert_eq!(unsigned(&output[0]["after"]), 0);
            bytes
        } else {
            assert_eq!(
                output[0]["outcome"],
                json!({"err": {"case": "budget-exhausted"}})
            );
            assert_eq!(unsigned(&output[0]["after"]), grant_bytes);
            assert!(backend.log_sink().snapshot().is_empty());
            0
        };
        assert_eq!(
            cancellation
                .accounting
                .snapshot_at(clock.monotonic_now())
                .log_bytes,
            consumed
        );
        assert_eq!(cancellation.accounting.outstanding_reservations(), 0);
    }
    assert_eq!(*sink.accepted.lock().expect("sink lock"), vec![expected]);
    let captured = backend.log_sink().snapshot();
    assert_eq!(captured.len(), 1);
    assert_eq!(captured[0].fields["latent.activation_id"], "exact-log");
    assert_eq!(captured[0].fields["activation_id"], "guest-claim");
    assert_eq!(captured[0].fields["latent.trace_id"], "trace-pinned");
    assert_eq!(captured[0].fields["latent.span_id"], "span-pinned");
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn sink_rejection_refunds_shared_budget_before_guest_retry() {
    let clock = Arc::new(ManualClock::new());
    let sink = Arc::new(RecordingSink::default());
    sink.reject_next.store(true, Ordering::Release);
    let mut services = services(&clock);
    services.log_sink = Some(sink.clone());
    let (backend, prepared) = prepared(config(), services).await;
    let mut grant = budget();
    grant.log_bytes = u64::try_from(expected_record().len()).expect("record bytes");
    let cancellation = Cancellation::new("exact-log", &grant, clock.sample());
    let request = request(
        &prepared,
        &cancellation,
        "log-twice",
        &json!([MESSAGE, fields()]),
    );
    let output = returned(run(&backend, request, &cancellation).await);
    let first = &output[0][0];
    let second = &output[0][1];
    assert_eq!(first["outcome"], json!({"err": {"case": "unavailable"}}));
    assert_eq!(unsigned(&first["before"]), grant.log_bytes);
    assert_eq!(unsigned(&first["after"]), grant.log_bytes);
    assert_eq!(second["outcome"], json!({"ok": true}));
    assert_eq!(unsigned(&second["before"]), grant.log_bytes);
    assert_eq!(unsigned(&second["after"]), 0);
    assert_eq!(
        *sink.accepted.lock().expect("sink lock"),
        vec![expected_record()]
    );
    assert_eq!(backend.log_sink().snapshot().len(), 1);
    assert_eq!(
        cancellation
            .accounting
            .snapshot_at(clock.monotonic_now())
            .log_bytes,
        grant.log_bytes
    );
    assert_eq!(cancellation.accounting.outstanding_reservations(), 0);
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn invalid_and_case_insensitive_reserved_fields_never_reach_sink_or_spend_budget() {
    let clock = Arc::new(ManualClock::new());
    let sink = Arc::new(RecordingSink::default());
    let mut services = services(&clock);
    services.log_sink = Some(sink.clone());
    let (backend, prepared) = prepared(config(), services).await;
    for invalid in [
        json!([{"name": "latent.activation_id", "value": "spoof"}]),
        json!([{"name": "LaTeNt.trace_id", "value": "spoof"}]),
        json!([{"name": "latent.custom", "value": "reserved"}]),
        json!([{"name": "bad key", "value": "space"}]),
        json!([{"name": "same", "value": "one"}, {"name": "same", "value": "two"}]),
    ] {
        let grant = budget();
        let cancellation = Cancellation::new("invalid-log", &grant, clock.sample());
        let request = request(
            &prepared,
            &cancellation,
            "log-probe",
            &json!(["message", invalid]),
        );
        let output = returned(run(&backend, request, &cancellation).await);
        assert_eq!(output[0]["outcome"]["err"]["case"], "invalid-field");
        assert_eq!(unsigned(&output[0]["after"]), grant.log_bytes);
        assert_eq!(
            cancellation
                .accounting
                .snapshot_at(clock.monotonic_now())
                .log_bytes,
            0
        );
    }
    assert!(sink.accepted.lock().expect("sink lock").is_empty());
    assert!(backend.log_sink().snapshot().is_empty());
}
