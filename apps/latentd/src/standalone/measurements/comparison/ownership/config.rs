use latent_core::ResourceBudget;
use latent_wasmtime::{ContextExposurePolicy, WasmtimeConfig};

pub(super) fn runtime() -> WasmtimeConfig {
    WasmtimeConfig {
        maximum_fuel: 10_000_000_000,
        maximum_memory_bytes: 67_108_864,
        fuel_async_yield_interval: Some(10_000),
        epoch_tick_interval_millis: 1,
        prepared_cache_maximum_entries: 4,
        maximum_concurrent_preparations: 4,
        compiler_workers: Some(2),
        maximum_active_instances: 4,
        context_policy: ContextExposurePolicy {
            metadata_prefixes: vec!["guest.".into()],
            claim_keys: vec!["role".into()],
            baggage_keys: vec!["locale".into()],
        },
        ..WasmtimeConfig::default()
    }
}

pub(super) fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 10_000_000_000,
        memory_bytes: 67_108_864,
        wall_time_limit_millis: Some(1000),
        log_bytes: 16_384,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    }
}
