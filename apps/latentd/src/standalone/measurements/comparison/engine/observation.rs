use super::{Clock, Node, Result};
use latent_core::{ActivationClock, ClockSample, DeadlineDiagnosticObserver, DeadlineWaitObserver};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

pub(super) struct ObservingClock {
    pub diagnostic: DeadlineDiagnosticObserver,
    pub waits: DeadlineWaitObserver,
    pub enabled: AtomicBool,
}
impl ActivationClock for ObservingClock {
    fn sample(&self) -> ClockSample {
        ClockSample::system_now()
    }
    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
    fn uses_system_monotonic(&self) -> bool {
        true
    }
    fn deadline_wait_observer(&self) -> Option<&DeadlineWaitObserver> {
        Some(&self.waits)
    }
    fn deadline_diagnostic_observer(&self) -> Option<&DeadlineDiagnosticObserver> {
        self.enabled
            .load(Ordering::Acquire)
            .then_some(&self.diagnostic)
    }
}
pub(super) fn decimals(value: &mut Value) {
    match value {
        Value::Number(n) => *value = json!(n.to_string()),
        Value::Array(a) => a.iter_mut().for_each(decimals),
        Value::Object(o) => o.values_mut().for_each(decimals),
        _ => {}
    }
}
pub(super) fn native(node: &Node) -> Value {
    native_snapshot(&node.owner.backend.resource_snapshot())
}
pub(super) fn native_snapshot(v: &latent_wasmtime::RuntimeResourceSnapshot) -> Value {
    json!({"active_invocations":v.active_invocations.to_string(),"live_stores":v.live_stores.to_string(),"live_host_states":v.live_host_states.to_string(),"live_component_instances":v.live_component_instances.to_string(),"live_temporary_buffers":v.live_temporary_buffers.to_string(),"live_cancellation_probes":v.live_cancellation_probes.to_string(),"stores_created":v.stores_created.to_string()})
}
pub(super) fn profile(node: &Node, plan: &super::plan::Plan) -> Result<Value> {
    let profile = node
        .owner
        .factory
        .as_ref()
        .ok_or("engine factory missing")?
        .profile();
    let c = &node.runtime_config;
    let pooled = profile.pooling_allocator;
    Ok(
        json!({"id":profile.id,"wasmtime_version":profile.wasmtime_version,"target_triple":profile.target_triple,"cpu_feature_set":profile.cpu_feature_set,
        "pooling_allocator":pooled,"copy_on_write_images":profile.copy_on_write_images,"async_support":profile.async_support,"fuel_enabled":profile.fuel_enabled,"epoch_interruption_enabled":profile.epoch_interruption_enabled,"configuration":profile.configuration,
        "effective_policy":{"source":"common-source-projection","allocator":c.instance_allocator.name(),
            "optimization":plan.requested_engine.as_ref().map_or("speed",|v|v.optimization.as_str()),
            "optimization_source":if plan.variant=="control" {"pinned-wasmtime-47.0.3-default"}else{"requested-config-bound-to-candidate-profile"},
            "memory_reservation_bytes":if pooled {c.maximum_memory_bytes.to_string()}else{"4294967296".into()},
            "memory_guard_bytes":if pooled {"0"}else{"33554432"},"memory_reservation_for_growth_bytes":if pooled {"0"}else{"2147483648"},
            "layout_source":if pooled {"existing-source-override"}else{"pinned-wasmtime-47.0.3-default"},
            "async_stack_zeroing":false,"memory_may_move":true,"guard_before_linear_memory":true,
            "pooling_maximum_instances":c.pooling_maximum_instances.to_string(),"maximum_active_instances":c.maximum_active_instances.to_string(),
            "pooling_unused_warm_slots":pooled.then_some("0"),"pooling_decommit_batch_size":pooled.then_some("1"),"pooling_keep_resident_bytes":pooled.then_some("0"),
            "maximum_memory_bytes":c.maximum_memory_bytes.to_string(),"async_stack_bytes":c.async_stack_bytes.to_string(),"maximum_wasm_stack_bytes":c.maximum_wasm_stack_bytes.to_string(),"fuel_async_yield_interval":c.fuel_async_yield_interval.map(|v|v.to_string())}}),
    )
}
pub(super) fn checkpoint(node: &Node, clock: Clock, label: &str) -> Result<Value> {
    let mut accounting = serde_json::to_value(node.owner.backend.cache_accounting_snapshot())?;
    decimals(&mut accounting);
    let mut compiler = serde_json::to_value(node.owner.backend.compiler_snapshot())?;
    decimals(&mut compiler);
    Ok(
        json!({"kind":"checkpoint","label":label,"node":node.sample(label)?,"native":native(node),"accounting":accounting,"compiler":compiler,
        "preparation":super::super::cold::observation::snapshot(&node.owner.backend.preparation_observer(),clock)?,"cleanup":node.owner.cleanup_snapshot(),
        "memory":super::resources::capture(label,clock)?,"cpu":if cfg!(target_os="linux") {super::super::budget::cpu::sample(clock)?}else{Value::Null}}),
    )
}
