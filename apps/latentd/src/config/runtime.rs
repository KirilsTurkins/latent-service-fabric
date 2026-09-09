use std::time::Duration;

use latent_core::PlatformError;
use latent_node::{LocalActivationJournalConfig, LocalActivationManagerConfig};
use latent_wasmtime::{CompilerOptimization, InstanceAllocator, WasmtimeConfig};
use latent_wire::invocation::InvocationLimits;
use latent_wire::management::ManagementLimits;

use super::validation::Capacity;
use super::{
    invalid, EngineAllocator, EngineOptimization, NodeConfig, CONTEXT_BYTES, IDENTIFIER_BYTES,
    JOURNAL_RECORD_BYTES, MIB,
};

pub(super) fn wasmtime(
    config: &NodeConfig,
    capacity: &Capacity,
) -> Result<WasmtimeConfig, PlatformError> {
    let mut runtime = WasmtimeConfig {
        instance_allocator: match config.engine.allocator {
            EngineAllocator::OnDemand => InstanceAllocator::OnDemand,
            EngineAllocator::Pooling => InstanceAllocator::Pooling,
        },
        compiler_optimization: match config.engine.optimization {
            EngineOptimization::Speed => CompilerOptimization::Speed,
            EngineOptimization::SpeedAndSize => CompilerOptimization::SpeedAndSize,
        },
        maximum_component_bytes: config.limits.maximum_component_bytes,
        maximum_memory_bytes: capacity.maximum_memory,
        maximum_fuel: config.execution.maximum_cpu_fuel,
        fuel_async_yield_interval: Some(10_000),
        maximum_active_instances: capacity.cells as usize,
        prepared_cache_maximum_entries: config.cache.entries,
        prepared_cache_maximum_source_bytes: config.cache.source_bytes,
        prepared_cache_maximum_metadata_bytes: config.cache.metadata_bytes,
        prepared_cache_maximum_compiled_image_bytes: config.cache.compiled_image_bytes,
        maximum_concurrent_preparations: config.cache.preparations,
        compiler_workers: config.cache.compiler_workers,
        maximum_preparation_waiters: capacity.reservations as usize,
        maximum_waiters_per_preparation: capacity.reservations as usize,
        maximum_ready_preparations: capacity.reservations as usize,
        maximum_preparation_document_bytes: preparation_documents(config)?,
        // Capture remains positive even if the effective grant denies logging.
        invocation_log_maximum_bytes: 16 * 1024,
        ..WasmtimeConfig::default()
    };
    if runtime.instance_allocator == InstanceAllocator::Pooling {
        // Capacity has passed checked aggregation across every cell class.
        // Keep the inactive on-demand pool setting at its historical default.
        runtime.pooling_maximum_instances = capacity.cells;
    }
    runtime.value_codec_limits.max_input_bytes = config.limits.maximum_payload_bytes;
    runtime.value_codec_limits.max_output_bytes = config.limits.maximum_payload_bytes;
    runtime.validate().map_err(|_| invalid("wasmtime"))?;
    Ok(runtime)
}

pub(super) fn manager(config: &NodeConfig, capacity: &Capacity) -> LocalActivationManagerConfig {
    LocalActivationManagerConfig {
        requests: latent_activation::ActivationRequestLimits {
            maximum_identifier_bytes: IDENTIFIER_BYTES,
            maximum_context_bytes: CONTEXT_BYTES,
            maximum_input_bytes: config.limits.maximum_payload_bytes,
        },
        journal: LocalActivationJournalConfig {
            maximum_active: capacity.reservations as usize,
            maximum_terminal: config.retention.terminal_entries,
            maximum_record_bytes: JOURNAL_RECORD_BYTES,
            maximum_retained_bytes: config.retention.bytes,
            terminal_retention: Duration::from_millis(config.retention.terminal_ttl_millis),
        },
        maximum_cancellation_reason_bytes: 256,
        cleanup_grace: Duration::from_millis(100),
    }
}

pub(super) fn invocation(
    config: &NodeConfig,
    capacity: &Capacity,
) -> Result<InvocationLimits, PlatformError> {
    let limits = InvocationLimits {
        max_payload_bytes: config.limits.maximum_payload_bytes,
        max_id_bytes: IDENTIFIER_BYTES,
        max_cancel_reason_bytes: 256,
        max_timeout_millis: config.execution.maximum_wall_time_millis,
        max_cpu_fuel: config.execution.maximum_cpu_fuel,
        max_memory_bytes: capacity.maximum_memory,
        max_log_bytes: config.execution.maximum_log_bytes,
        ..InvocationLimits::default()
    };
    limits.validate().map_err(|_| invalid("invocation"))?;
    Ok(limits)
}

pub(super) fn management(
    config: &NodeConfig,
    invocation: &InvocationLimits,
) -> Result<ManagementLimits, PlatformError> {
    let limits = ManagementLimits {
        auth: invocation.clone(),
        max_request_bytes: config
            .limits
            .maximum_component_bytes
            .checked_add(4 * MIB)
            .ok_or_else(|| invalid("limits.maximumComponentBytes"))?,
        max_component_bytes: config.limits.maximum_component_bytes,
        max_id_bytes: IDENTIFIER_BYTES,
        // Artifact tokens are fixed 101 bytes; deployment tokens embed three
        // hex-encoded identifiers plus a fixed bounded protocol envelope.
        max_page_token_bytes: (64 + 6 * IDENTIFIER_BYTES).max(101),
        ..ManagementLimits::default()
    };
    limits.validate().map_err(|_| invalid("management"))?;
    Ok(limits)
}

fn preparation_documents(config: &NodeConfig) -> Result<usize, PlatformError> {
    // These are the same repository/codec defaults used by standalone startup.
    // The limit covers encoded inputs plus fixed reader/job allowance, not the
    // allocator's transient JSON decoder or Wasmtime compiler heap usage.
    latent_artifacts::DirectoryArtifactRepositoryConfig::default()
        .max_metadata_bytes
        .checked_add(latent_manifest::ManifestLimits::default().max_document_bytes)
        .and_then(|bytes| bytes.checked_add(64 * 1024))
        .and_then(|bytes| bytes.checked_mul(config.cache.preparations))
        .ok_or_else(|| invalid("cache.preparations"))
}
