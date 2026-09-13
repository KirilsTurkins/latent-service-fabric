use wasmtime::{Config, OptLevel, PoolingAllocationConfig, WasmBacktraceDetails};

use super::layout::{
    ASYNC_STACK_ZEROING, POOL_DECOMMIT_BATCH_SIZE, POOL_KEEP_RESIDENT_BYTES, POOL_UNUSED_WARM_SLOTS,
};
use super::{CompilerOptimization, InstanceAllocator, WasmtimeConfig};
use latent_core::PlatformError;

/// Closed code-generation settings shared by the runtime and compiler bootstrap.
/// Applying these does not construct a pooling allocator or an execution Store.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct CompilerEngineSettings {
    optimization: Optimization,
    maximum_wasm_stack_bytes: usize,
    async_stack_bytes: usize,
    memory: super::layout::MemoryLayout,
    copy_on_write_images: bool,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
enum Optimization {
    Speed,
    SpeedAndSize,
}

impl CompilerEngineSettings {
    pub(crate) fn from_config(config: &WasmtimeConfig) -> Self {
        Self {
            optimization: match config.compiler_optimization {
                CompilerOptimization::Speed => Optimization::Speed,
                CompilerOptimization::SpeedAndSize => Optimization::SpeedAndSize,
            },
            maximum_wasm_stack_bytes: config.maximum_wasm_stack_bytes,
            async_stack_bytes: config.async_stack_bytes,
            memory: config.memory_layout(),
            copy_on_write_images: config.copy_on_write_images,
        }
    }
    pub(crate) fn validate_compiler(&self) -> Result<(), PlatformError> {
        if self.maximum_wasm_stack_bytes == 0
            || self.maximum_wasm_stack_bytes > 64 * 1024 * 1024
            || self.async_stack_bytes < self.maximum_wasm_stack_bytes
            || self.async_stack_bytes > 128 * 1024 * 1024
            || !self.memory.compiler_bounded()
        {
            return Err(super::invalid_config());
        }
        Ok(())
    }
    pub(crate) fn apply(&self, engine_config: &mut Config) {
        engine_config.cranelift_opt_level(match self.optimization {
            Optimization::Speed => OptLevel::Speed,
            Optimization::SpeedAndSize => OptLevel::SpeedAndSize,
        });
        engine_config.wasm_component_model(true);
        engine_config.wasm_component_model_async(true);
        engine_config.consume_fuel(true);
        engine_config.epoch_interruption(true);
        engine_config.max_wasm_stack(self.maximum_wasm_stack_bytes);
        engine_config.async_stack_size(self.async_stack_bytes);
        engine_config.async_stack_zeroing(ASYNC_STACK_ZEROING);
        self.memory.apply(engine_config);
        engine_config.memory_init_cow(self.copy_on_write_images);
        engine_config.wasm_backtrace_details(WasmBacktraceDetails::Disable);
        engine_config.wasm_backtrace_max_frames(None);
    }
}

impl WasmtimeConfig {
    pub(crate) fn apply_engine(&self, engine_config: &mut Config) -> Result<(), PlatformError> {
        self.validate()?;
        CompilerEngineSettings::from_config(self).apply(engine_config);
        if matches!(self.instance_allocator, InstanceAllocator::Pooling) {
            self.apply_pooling(engine_config);
        }
        Ok(())
    }

    fn apply_pooling(&self, engine_config: &mut Config) {
        // validate_pooling checked every multiplication before engine mutation.
        let mut pooling = PoolingAllocationConfig::new();
        pooling
            .total_component_instances(self.pooling_maximum_instances)
            .total_core_instances(
                self.pooling_maximum_instances * self.pooling_maximum_core_instances_per_component,
            )
            .total_memories(
                self.pooling_maximum_instances * self.pooling_maximum_memories_per_component,
            )
            .total_tables(
                self.pooling_maximum_instances * self.pooling_maximum_tables_per_component,
            )
            .total_stacks(self.pooling_maximum_instances)
            .max_component_instance_size(self.pooling_maximum_component_instance_bytes)
            .max_core_instance_size(self.pooling_maximum_core_instance_bytes)
            .max_core_instances_per_component(self.pooling_maximum_core_instances_per_component)
            .max_memories_per_component(self.pooling_maximum_memories_per_component)
            .max_tables_per_component(self.pooling_maximum_tables_per_component)
            .max_memory_size(
                usize::try_from(self.maximum_memory_bytes).expect("validated host memory bound"),
            )
            .table_elements(self.maximum_table_elements)
            .max_unused_warm_slots(POOL_UNUSED_WARM_SLOTS)
            .decommit_batch_size(POOL_DECOMMIT_BATCH_SIZE)
            .async_stack_keep_resident(POOL_KEEP_RESIDENT_BYTES)
            .linear_memory_keep_resident(POOL_KEEP_RESIDENT_BYTES)
            .table_keep_resident(POOL_KEEP_RESIDENT_BYTES);
        engine_config.allocation_strategy(pooling);
    }
}
