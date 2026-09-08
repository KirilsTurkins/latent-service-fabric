use latent_activation::TraceContext;
use latent_core::Metadata;
use latent_telemetry::TelemetryRecord;
use latent_wire::invocation::proto;
use serde_json::{json, Value};

use super::{fixture, StandaloneNode};

pub async fn observe(
    node: &StandaloneNode,
    response: &proto::InvokeResponse,
    tenant: &str,
    root: &str,
    parent: &str,
    expected_logs: usize,
) -> Value {
    tokio::time::timeout(std::time::Duration::from_secs(2), node.telemetry.flush())
        .await
        .unwrap()
        .unwrap();
    let mut spans = Vec::new();
    let mut logs = Vec::new();
    for record in node.sink.records() {
        match record {
            TelemetryRecord::Span(span)
                if span.attributes.get("activation_id") == Some(&response.activation_id) =>
            {
                assert_eq!(span.name, "latent.activation");
                assert_eq!(span.status, "ok");
                assert!(span.ended_at_unix_nanos >= span.started_at_unix_nanos);
                correlation(
                    &span.attributes,
                    &span.trace,
                    response,
                    tenant,
                    root,
                    parent,
                );
                spans.push(json!({"name":span.name,"status":span.status,"attributes":span.attributes,
                    "trace":trace(&span.trace),"started_at_unix_nanos":span.started_at_unix_nanos.to_string(),
                    "ended_at_unix_nanos":span.ended_at_unix_nanos.to_string()}));
            }
            TelemetryRecord::Log(log)
                if log.attributes.get("activation_id") == Some(&response.activation_id)
                    && !log.attributes.contains_key("stage") =>
            {
                assert_eq!(log.body, "[REDACTED]");
                let observed_trace = log.trace.as_ref().expect("guest log trace");
                correlation(
                    &log.attributes,
                    observed_trace,
                    response,
                    tenant,
                    root,
                    parent,
                );
                assert!(!log.attributes.keys().any(|key| key.starts_with("guest.")));
                logs.push(json!({"body":log.body,"attributes":log.attributes,"trace":trace(observed_trace),
                    "observed_at_unix_millis":log.observed_at_unix_millis.to_string()}));
            }
            _ => {}
        }
    }
    assert_eq!(spans.len(), 1, "one committed activation span");
    assert_eq!(logs.len(), expected_logs, "actual accepted guest logs");
    for log in &logs {
        assert_eq!(log["trace"], spans[0]["trace"]);
    }
    let consumption = response.consumption.as_ref().unwrap();
    for (name, value) in [
        ("cpu_fuel", consumption.cpu_fuel),
        ("memory_bytes", consumption.peak_memory_bytes),
        ("wall_time_micros", consumption.wall_time_micros),
        ("log_bytes", consumption.log_bytes),
    ] {
        assert_eq!(spans[0]["attributes"][name], value.to_string());
    }
    json!({"activation_id":response.activation_id,"root_activation_id":root,"parent_activation_id":parent,
        "tenant":tenant,"service":fixture::SHARED,"release_digest":response.release_digest,
        "revision_id":response.revision_id,"route_generation":response.route_generation.to_string(),
        "completion_span":spans.remove(0),"guest_logs":logs})
}

fn correlation(
    attributes: &Metadata,
    observed: &TraceContext,
    response: &proto::InvokeResponse,
    tenant: &str,
    root: &str,
    parent: &str,
) {
    for (name, expected) in [
        ("activation_id", response.activation_id.as_str()),
        ("root_activation_id", root),
        ("parent_activation_id", parent),
        ("tenant", tenant),
        ("service", fixture::SHARED),
        ("release", response.release_digest.as_str()),
        ("revision", response.revision_id.as_str()),
    ] {
        assert_eq!(attributes.get(name).map(String::as_str), Some(expected));
    }
    assert_eq!(
        attributes["route_generation"],
        response.route_generation.to_string()
    );
    assert_eq!(observed.trace_id.0.len(), 32);
    assert_eq!(observed.span_id.0.len(), 16);
    assert!(observed
        .trace_id
        .0
        .bytes()
        .all(|byte| byte.is_ascii_hexdigit()));
    assert!(observed
        .span_id
        .0
        .bytes()
        .all(|byte| byte.is_ascii_hexdigit()));
    assert!(observed.baggage.is_empty());
}

pub fn trace(value: &TraceContext) -> Value {
    json!({"trace_id":value.trace_id.0,"span_id":value.span_id.0,"trace_flags":value.trace_flags,
        "baggage":value.baggage})
}
