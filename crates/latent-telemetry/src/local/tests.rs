use super::*;
use crate::LogSeverity;
use latent_activation::TraceContext;
use latent_core::{Metadata, SpanId, TraceId};
fn log(body: &str) -> LogRecord {
    LogRecord {
        severity: LogSeverity::Info,
        body: body.to_owned(),
        trace: None,
        attributes: Metadata::new(),
        observed_at_unix_millis: 1,
    }
}
fn trace() -> TraceContext {
    TraceContext {
        trace_id: TraceId("trace".into()),
        span_id: SpanId("span".into()),
        trace_flags: 1,
        baggage: Metadata::new(),
    }
}

#[tokio::test]
async fn local_sink_evicts_oldest_records_under_entry_and_byte_bounds() {
    let bytes = retained_bytes(&TelemetryRecord::Log(log("first")), usize::MAX).unwrap();
    let sink = StructuredLocalSink::new(LocalSinkConfig {
        maximum_entries: 2,
        maximum_bytes: bytes * 2 + 32,
    })
    .unwrap();
    for body in ["first", "second", "third"] {
        sink.emit_log(log(body)).await.unwrap();
    }
    assert_eq!(sink.snapshot().entries, 2);
    assert_eq!(sink.snapshot().evicted_entries, 1);
    let TelemetryRecord::Log(first) = &sink.records()[0] else {
        panic!("expected log")
    };
    assert_eq!(first.body, "second");
    let mut larger = log("last");
    larger.body = "x".repeat(bytes);
    sink.emit_log(larger).await.unwrap();
    assert_eq!(sink.snapshot().entries, 1);
    assert_eq!(sink.snapshot().evicted_entries, 3);
    assert!(sink.snapshot().retained_bytes <= sink.snapshot().maximum_bytes);
    sink.clear();
    assert_eq!(sink.snapshot().retained_bytes, 0);
    assert!(sink.records().is_empty());
}

#[tokio::test]
async fn direct_sink_accounts_baggage_and_spare_capacity_for_logs_and_spans() {
    let sink = StructuredLocalSink::new(LocalSinkConfig {
        maximum_entries: 2,
        maximum_bytes: 16 * 1024,
    })
    .unwrap();
    let mut trace = trace();
    let mut value = String::with_capacity(32 * 1024);
    value.push('x');
    trace.baggage.insert("small".into(), value);
    let mut record = log("small");
    record.trace = Some(trace);
    assert_eq!(
        sink.emit_log(record).await.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut trace = self::trace();
    trace.baggage.insert("large".into(), "x".repeat(32 * 1024));
    let span = SpanRecord {
        name: "span".into(),
        trace,
        parent_span_id: None,
        started_at_unix_nanos: 1,
        ended_at_unix_nanos: 2,
        status: "ok".into(),
        attributes: Metadata::new(),
    };
    assert!(sink.emit_span(span).await.is_err());
    assert_eq!(sink.snapshot().dropped_oversized, 2);
    assert_eq!(sink.snapshot().entries, 0);
    assert_eq!(sink.snapshot().retained_bytes, 0);
}

#[tokio::test]
async fn bounded_records_preserve_structured_fields_without_implicit_payloads() {
    let sink = StructuredLocalSink::new(LocalSinkConfig::default()).unwrap();
    let mut record = log("redacted");
    let mut trace = trace();
    trace.baggage.insert("allowed".into(), "value".into());
    record.trace = Some(trace);
    record
        .attributes
        .insert("activation_id".into(), "activation-1".into());
    sink.emit_log(record.clone()).await.unwrap();
    assert_eq!(sink.records(), vec![TelemetryRecord::Log(record)]);
    assert!(sink.snapshot().retained_bytes > "redacted".len());
}

#[test]
fn impossible_sink_bounds_are_rejected() {
    for config in [
        LocalSinkConfig {
            maximum_entries: 0,
            maximum_bytes: 1,
        },
        LocalSinkConfig {
            maximum_entries: usize::MAX,
            maximum_bytes: 1,
        },
        LocalSinkConfig {
            maximum_entries: 1,
            maximum_bytes: usize::MAX,
        },
    ] {
        assert!(StructuredLocalSink::new(config).is_err());
    }
}
