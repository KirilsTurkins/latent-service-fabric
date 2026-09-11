use super::Result;
use latent_core::{BudgetConsumption, ResourceBudget};
use latent_wasmtime::{InvocationInputObserver, RuntimeResourceSnapshot, WasmtimeBackend};
use serde_json::{json, Value};
use std::time::Instant;

pub(super) fn elapsed(origin: Instant) -> String {
    origin.elapsed().as_nanos().to_string()
}
pub(super) fn resources(v: RuntimeResourceSnapshot) -> Value {
    json!({"active_invocations":v.active_invocations.to_string(),"live_stores":v.live_stores.to_string(),
        "live_host_states":v.live_host_states.to_string(),"live_component_instances":v.live_component_instances.to_string(),
        "live_temporary_buffers":v.live_temporary_buffers.to_string(),"live_cancellation_probes":v.live_cancellation_probes.to_string(),
        "stores_created":v.stores_created.to_string()})
}
pub(super) fn idle(backend: &WasmtimeBackend) -> Result<()> {
    let v = backend.resource_snapshot();
    if [
        v.active_invocations,
        v.live_stores,
        v.live_host_states,
        v.live_component_instances,
        v.live_temporary_buffers,
        v.live_cancellation_probes,
    ]
    .iter()
    .any(|n| *n != 0)
    {
        return Err("ownership backend resources remain".into());
    }
    Ok(())
}
pub(super) fn budget(v: &ResourceBudget) -> Value {
    json!({"cpu_fuel":v.cpu_fuel.to_string(),"memory_bytes":v.memory_bytes.to_string(),
        "wall_time_limit_millis":v.wall_time_limit_millis.map(|n|n.to_string()),"log_bytes":v.log_bytes.to_string(),
        "child_calls":v.child_calls.to_string(),"outbound_requests":v.outbound_requests.to_string(),
        "state_read_bytes":v.state_read_bytes.to_string(),"state_write_bytes":v.state_write_bytes.to_string(),
        "blob_read_bytes":v.blob_read_bytes.to_string(),"blob_write_bytes":v.blob_write_bytes.to_string(),
        "effect_count":v.effect_count.to_string()})
}
pub(super) fn consumption(v: &BudgetConsumption) -> Value {
    json!({"cpu_fuel":v.cpu_fuel.to_string(),"peak_memory_bytes":v.peak_memory_bytes.to_string(),
        "wall_time_micros":v.wall_time_micros.to_string(),"log_bytes":v.log_bytes.to_string(),
        "child_calls":v.child_calls.to_string(),"outbound_requests":v.outbound_requests.to_string(),
        "state_read_bytes":v.state_read_bytes.to_string(),"state_write_bytes":v.state_write_bytes.to_string(),
        "blob_read_bytes":v.blob_read_bytes.to_string(),"blob_write_bytes":v.blob_write_bytes.to_string(),
        "effect_count":v.effect_count.to_string()})
}
pub(super) fn input(observer: &InvocationInputObserver, origin: Instant) -> Result<Value> {
    let started = elapsed(origin);
    let mut snapshot = serde_json::to_value(observer.snapshot())?;
    decimal(&mut snapshot);
    Ok(
        json!({"capture_started_nanos":started,"capture_finished_nanos":elapsed(origin),
        "origin_offset_nanos":observer.origin().checked_duration_since(origin).ok_or("ownership observer origin")?.as_nanos().to_string(),
        "snapshot":snapshot}),
    )
}
fn decimal(value: &mut Value) {
    match value {
        Value::Number(n) => *value = Value::String(n.to_string()),
        Value::Array(a) => {
            for v in a {
                decimal(v);
            }
        }
        Value::Object(m) => {
            for v in m.values_mut() {
                decimal(v);
            }
        }
        _ => {}
    }
}
