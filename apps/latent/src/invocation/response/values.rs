use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::{ActivationTerminalState, BudgetConsumption, CancelDisposition, DeclaredError};
use serde_json::{json, Value};

pub(super) fn payload(bytes: &[u8], media: &str) -> Value {
    json!({"encoding": "base64", "mediaType": media, "data": STANDARD.encode(bytes),
        "byteLength": bytes.len().to_string()})
}

pub(super) fn consumption(value: &BudgetConsumption) -> Value {
    json!({"cpuFuel": value.cpu_fuel.to_string(), "peakMemoryBytes": value.peak_memory_bytes.to_string(),
        "wallTimeMicros": value.wall_time_micros.to_string(), "childCalls": value.child_calls,
        "outboundRequests": value.outbound_requests, "stateReadBytes": value.state_read_bytes.to_string(),
        "stateWriteBytes": value.state_write_bytes.to_string(), "blobReadBytes": value.blob_read_bytes.to_string(),
        "blobWriteBytes": value.blob_write_bytes.to_string(), "logBytes": value.log_bytes.to_string(), "effectCount": value.effect_count})
}

pub(super) fn declared(value: &DeclaredError) -> Value {
    json!({"code": value.code, "message": value.message,
        "payload": payload(&value.payload, &value.media_type), "metadata": value.metadata})
}

pub(super) fn terminal(value: ActivationTerminalState) -> Option<String> {
    latent_wire::invocation::cancel_disposition_to_proto(CancelDisposition::AlreadyTerminal(value))
        .terminal_state
}
