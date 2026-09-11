use latent_wire::invocation::proto;
use serde_json::{json, Value};

use super::super::fixture;
use super::{FUEL, LOG, MEMORY, WALL};

pub fn call(
    response: &proto::InvokeResponse,
    status: &proto::ActivationStatus,
    mut telemetry: Value,
) -> Value {
    let Some(proto::invoke_response::Result::Success(success)) = &response.result else {
        panic!(
            "capability must return a typed success: {:?}",
            response.result
        );
    };
    assert_eq!(success.media_type, latent_wasmtime::WIT_VALUES_MEDIA_TYPE);
    assert_eq!(success.metadata["cell-id"], fixture::CELL);
    assert_eq!(success.metadata["cell-disposition"], "released");
    assert!(success.committed_state_version.is_none() && success.effect_ids.is_empty());
    assert_eq!(status.activation_id, response.activation_id);
    assert_eq!(status.terminal_state.as_deref(), Some("completed"));
    assert_eq!(status.final_consumption, response.consumption);
    assert!(status.terminal_at_unix_millis.is_some());
    let Some(proto::activation_status::TerminalOutcome::Succeeded(retained)) =
        &status.terminal_outcome
    else {
        panic!("retained capability success");
    };
    assert_eq!(retained.metadata, success.metadata);
    assert_eq!(
        retained.committed_state_version,
        success.committed_state_version
    );
    assert_eq!(retained.effect_ids, success.effect_ids);
    let decoded: Value = serde_json::from_slice(&success.payload).unwrap();
    assert_eq!(decoded.as_array().unwrap().len(), 1);
    assert!(!decoded.to_string().contains("private-context-marker"));
    telemetry["cell_id"] = json!(success.metadata["cell-id"]);
    telemetry["decoded"] = decoded;
    telemetry["consumption"] = consumption(response.consumption.as_ref().unwrap());
    telemetry["grant"] = json!({"cpu_fuel":FUEL.to_string(),"memory_bytes":MEMORY.to_string(),
        "log_bytes":LOG.to_string(),"wall_time_limit_millis":WALL.to_string()});
    telemetry["retained_status"] = json!({
        "activation_id":status.activation_id,"phase":status.phase,"terminal_state":status.terminal_state,
        "final_consumption":consumption(status.final_consumption.as_ref().unwrap()),
        "terminal_at_unix_millis":status.terminal_at_unix_millis.unwrap().to_string(),
        "last_updated_unix_millis":status.last_updated_unix_millis.to_string(),
        "metadata":status.metadata,"terminal_kind":"success"});
    telemetry
}

fn consumption(value: &proto::BudgetConsumption) -> Value {
    assert!(value.cpu_fuel > 0 && value.cpu_fuel <= FUEL);
    assert!(value.peak_memory_bytes > 0 && value.peak_memory_bytes <= MEMORY);
    assert!(value.log_bytes <= LOG);
    assert!(value.wall_time_micros <= (WALL + 500) * 1000);
    for value in [
        u64::from(value.child_calls),
        u64::from(value.outbound_requests),
        value.state_read_bytes,
        value.state_write_bytes,
        value.blob_read_bytes,
        value.blob_write_bytes,
        u64::from(value.effect_count),
    ] {
        assert_eq!(value, 0);
    }
    json!({"cpu_fuel":value.cpu_fuel.to_string(),"peak_memory_bytes":value.peak_memory_bytes.to_string(),
        "wall_time_micros":value.wall_time_micros.to_string(),"log_bytes":value.log_bytes.to_string(),
        "child_calls":"0","outbound_requests":"0","state_read_bytes":"0","state_write_bytes":"0",
        "blob_read_bytes":"0","blob_write_bytes":"0","effect_count":"0"})
}
