use wasmtime::{Config, PoolingAllocationConfig, WasmBacktraceDetails};

use super::{InstanceAllocator, WasmtimeConfig};
use latent_core::PlatformError;

impl WasmtimeConfig {
    pub(crate) fn apply_engine(&self, engine_config: &mut Config) -> Result<(), PlatformError> {
        self.validate()?;
        engine_config.wasm_component_model(true);
        engine_config.wasm_component_model_async(true);
        engine_config.consume_fuel(true);
        engine_config.epoch_interruption(true);
        engine_config.max_wasm_stack(self.maximum_wasm_stack_bytes);
        engine_config.async_stack_size(self.async_stack_bytes);
        engine_config.memory_init_cow(self.copy_on_write_images);
        engine_config.wasm_backtrace_details(WasmBacktraceDetails::Disable);
        engine_config.wasm_backtrace_max_frames(None);
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
            .max_unused_warm_slots(0)
            .decommit_batch_size(1)
            .async_stack_keep_resident(0)
            .linear_memory_keep_resident(0)
            .table_keep_resident(0);
        engine_config.memory_reservation(self.maximum_memory_bytes);
        engine_config.memory_reservation_for_growth(0);
        engine_config.memory_guard_size(0);
        engine_config.allocation_strategy(pooling);
    }
}
