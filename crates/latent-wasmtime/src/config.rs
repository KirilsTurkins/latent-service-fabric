//! Explicit node policy shared by generic execution and the Phase 0 facade.

mod compiler;
mod engine;
pub(crate) use engine::CompilerEngineSettings;
mod layout;
mod pooling;
mod profile;
mod runtime_compatibility;
#[cfg(test)]
mod tests;

use latent_core::{PlatformError, PlatformErrorCode};

use crate::cache::CacheLimits;
use crate::containment::platform_error;
use crate::host::policy::ContextExposurePolicy;
use crate::values::ValueCodecLimits;

pub const WASMTIME_VERSION: &str = "47.0.3";
pub const GENERIC_BACKEND_ID: &str = "wasmtime-component-phase-1";
pub const PHASE0_BACKEND_ID: &str = "wasmtime-component-phase-0";
const MAXIMUM_EPOCH_OBSERVATION_MILLIS: u64 = 1_000;

/// Payload adaptation is part of prepared-state compatibility.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DispatchMode {
    Generic,
    Phase0,
}

impl DispatchMode {
    pub(crate) const fn backend_id(self) -> &'static str {
        match self {
            Self::Generic => GENERIC_BACKEND_ID,
            Self::Phase0 => PHASE0_BACKEND_ID,
        }
    }
}

/// Node-owned allocation strategy; neither mode retains service instances.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InstanceAllocator {
    OnDemand,
    Pooling,
}

impl InstanceAllocator {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::OnDemand => "on_demand",
            Self::Pooling => "pooling",
        }
    }
}

/// Compatibility name retained for the Phase 0 profiling facade.
pub type Phase0InstanceAllocator = InstanceAllocator;

/// Safe Cranelift optimization policies; neither choice changes containment.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompilerOptimization {
    Speed,
    SpeedAndSize,
}

impl CompilerOptimization {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Speed => "speed",
            Self::SpeedAndSize => "speed-and-size",
        }
    }
}

/// Hard node limits for compilation, retained preparation and fresh stores.
///
/// Component Model async execution, fuel and epoch interruption are required;
/// this policy cannot disable those containment mechanisms. Native host CPU
/// detection is retained. `cpu_feature_set` is a bounded compatibility label,
/// not a request to enable arbitrary compiler features or load portable AOT.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WasmtimeConfig {
    pub target_triple: String,
    pub cpu_feature_set: String,
    pub maximum_component_bytes: usize,
    pub maximum_memory_bytes: u64,
    pub maximum_fuel: u64,
    /// Optional positive fuel interval for cooperative async yields. It does
    /// not replenish fuel or change the activation's granted CPU allowance.
    pub fuel_async_yield_interval: Option<u64>,
    pub maximum_wasm_stack_bytes: usize,
    pub async_stack_bytes: usize,
    pub prepared_cache_maximum_entries: usize,
    pub prepared_cache_maximum_source_bytes: usize,
    /// False selects the legacy runner-scoped, non-reusable profiling slot.
    pub prepared_cache_enabled: bool,
    pub invocation_log_maximum_entries: usize,
    pub invocation_log_maximum_bytes: usize,
    pub retained_log_maximum_entries: usize,
    pub retained_log_maximum_bytes: usize,
    pub epoch_deadline_ticks: u64,
    /// Interval and interval-times-ticks are both bounded to one second.
    pub epoch_tick_interval_millis: u64,
    pub instance_allocator: InstanceAllocator,
    pub compiler_optimization: CompilerOptimization,
    pub copy_on_write_images: bool,
    pub pooling_maximum_instances: u32,
    pub maximum_artifact_metadata_bytes: usize,
    pub prepared_cache_maximum_metadata_bytes: usize,
    /// Compiled image address ranges, not total compiler heap or process RSS.
    pub prepared_cache_maximum_compiled_image_bytes: usize,
    pub maximum_concurrent_preparations: usize,
    /// Fixed generic compiler workers; None resolves to min(2, job capacity).
    pub compiler_workers: Option<usize>,
    pub maximum_preparation_waiters: usize,
    pub maximum_waiters_per_preparation: usize,
    pub maximum_ready_preparations: usize,
    /// Aggregate reserved encoded documents and fixed reader scratch.
    pub maximum_preparation_document_bytes: usize,
    /// Shared across all backends created by one factory, including on-demand.
    pub maximum_active_instances: usize,
    pub maximum_instances_per_store: usize,
    pub maximum_memories_per_store: usize,
    pub maximum_tables_per_store: usize,
    pub maximum_table_elements: usize,
    pub pooling_maximum_component_instance_bytes: usize,
    pub pooling_maximum_core_instance_bytes: usize,
    pub pooling_maximum_core_instances_per_component: u32,
    pub pooling_maximum_memories_per_component: u32,
    pub pooling_maximum_tables_per_component: u32,
    /// Per-transfer Component Model lifting allowance for generic execution.
    pub hostcall_fuel: usize,
    pub value_codec_limits: ValueCodecLimits,
    pub context_policy: ContextExposurePolicy,
}

/// Compatibility name retaining every old field and its default value.
pub type Phase0WasmtimeConfig = WasmtimeConfig;

impl Default for WasmtimeConfig {
    fn default() -> Self {
        Self {
            target_triple: env!("LATENT_WASMTIME_HOST_TARGET").to_owned(),
            cpu_feature_set: "host-baseline".to_owned(),
            maximum_component_bytes: 16 * 1024 * 1024,
            maximum_memory_bytes: 64 * 1024 * 1024,
            maximum_fuel: 100_000_000,
            fuel_async_yield_interval: None,
            maximum_wasm_stack_bytes: 512 * 1024,
            async_stack_bytes: 2 * 1024 * 1024,
            prepared_cache_maximum_entries: 8,
            prepared_cache_maximum_source_bytes: 64 * 1024 * 1024,
            prepared_cache_enabled: true,
            invocation_log_maximum_entries: 8,
            invocation_log_maximum_bytes: 16 * 1024,
            retained_log_maximum_entries: 256,
            retained_log_maximum_bytes: 512 * 1024,
            epoch_deadline_ticks: 1,
            epoch_tick_interval_millis: 5,
            instance_allocator: InstanceAllocator::OnDemand,
            compiler_optimization: CompilerOptimization::Speed,
            copy_on_write_images: true,
            pooling_maximum_instances: 1,
            maximum_artifact_metadata_bytes: 1024 * 1024,
            prepared_cache_maximum_metadata_bytes: 8 * 1024 * 1024,
            prepared_cache_maximum_compiled_image_bytes: 128 * 1024 * 1024,
            maximum_concurrent_preparations: 2,
            compiler_workers: None,
            maximum_preparation_waiters: 64,
            maximum_waiters_per_preparation: 64,
            maximum_ready_preparations: 64,
            maximum_preparation_document_bytes: 64 * 1024 * 1024,
            maximum_active_instances: 64,
            maximum_instances_per_store: 128,
            maximum_memories_per_store: 16,
            maximum_tables_per_store: 128,
            maximum_table_elements: 10_000,
            pooling_maximum_component_instance_bytes: 1024 * 1024,
            pooling_maximum_core_instance_bytes: 1024 * 1024,
            pooling_maximum_core_instances_per_component: 4,
            pooling_maximum_memories_per_component: 2,
            pooling_maximum_tables_per_component: 2,
            hostcall_fuel: 128 * 1024,
            value_codec_limits: ValueCodecLimits::default(),
            context_policy: ContextExposurePolicy::default(),
        }
    }
}

impl WasmtimeConfig {
    pub fn validate(&self) -> Result<(), PlatformError> {
        let positive = [
            self.maximum_component_bytes,
            self.maximum_wasm_stack_bytes,
            self.async_stack_bytes,
            self.maximum_artifact_metadata_bytes,
            self.maximum_active_instances,
            self.maximum_instances_per_store,
            self.invocation_log_maximum_entries,
            self.invocation_log_maximum_bytes,
            self.retained_log_maximum_entries,
            self.retained_log_maximum_bytes,
            self.hostcall_fuel,
        ];
        if self.target_triple != env!("LATENT_WASMTIME_HOST_TARGET")
            || self.cpu_feature_set.is_empty()
            || self.cpu_feature_set.len() > 256
            || positive.contains(&0)
            || self.maximum_memory_bytes == 0
            || usize::try_from(self.maximum_memory_bytes).is_err()
            || self.maximum_fuel == 0
            || self.fuel_async_yield_interval == Some(0)
            || self.async_stack_bytes < self.maximum_wasm_stack_bytes
            || self.epoch_deadline_ticks == 0
            || self.epoch_tick_interval_millis == 0
            || self
                .epoch_deadline_ticks
                .checked_mul(self.epoch_tick_interval_millis)
                .is_none_or(|millis| millis > MAXIMUM_EPOCH_OBSERVATION_MILLIS)
        {
            return Err(invalid_config());
        }
        if matches!(self.instance_allocator, InstanceAllocator::Pooling) {
            self.validate_pooling()?;
        }
        self.cache_limits().validate()?;
        self.validate_compiler()?;
        self.context_policy.validate()?;
        self.value_codec_limits.validate()
    }

    pub(crate) fn cache_limits(&self) -> CacheLimits {
        CacheLimits {
            maximum_entries: self.prepared_cache_maximum_entries,
            maximum_source_bytes: self.prepared_cache_maximum_source_bytes,
            maximum_metadata_bytes: self.prepared_cache_maximum_metadata_bytes,
            maximum_compiled_image_bytes: self.prepared_cache_maximum_compiled_image_bytes,
            maximum_concurrent_preparations: self.maximum_concurrent_preparations,
        }
    }

    pub(crate) fn active_instance_limit(&self) -> usize {
        match self.instance_allocator {
            InstanceAllocator::OnDemand => self.maximum_active_instances,
            InstanceAllocator::Pooling => self
                .maximum_active_instances
                .min(usize::try_from(self.pooling_maximum_instances).unwrap_or(usize::MAX)),
        }
    }

    fn validate_pooling(&self) -> Result<(), PlatformError> {
        if self.pooling_maximum_instances == 0
            || self.pooling_maximum_component_instance_bytes == 0
            || self.pooling_maximum_core_instance_bytes == 0
            || self.pooling_maximum_core_instances_per_component == 0
            || [
                self.pooling_maximum_core_instances_per_component,
                self.pooling_maximum_memories_per_component,
                self.pooling_maximum_tables_per_component,
            ]
            .into_iter()
            .any(|count| self.pooling_maximum_instances.checked_mul(count).is_none())
        {
            return Err(invalid_config());
        }
        self.validate_pooling_products()?;
        Ok(())
    }
}

fn invalid_config() -> PlatformError {
    platform_error(
        PlatformErrorCode::InvalidArgument,
        "invalid Wasmtime configuration",
        false,
    )
}
