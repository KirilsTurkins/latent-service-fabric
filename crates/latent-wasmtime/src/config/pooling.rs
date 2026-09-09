use latent_core::PlatformError;

use super::{invalid_config, WasmtimeConfig};

impl WasmtimeConfig {
    pub(super) fn validate_pooling_products(&self) -> Result<(), PlatformError> {
        // Count products have already been checked as u32. Also reject host
        // address-space overflow before Wasmtime reserves any pool. This is
        // arithmetic validation of configured capacities, not an RSS estimate:
        // mapping alignment, guards and allocator metadata add overhead.
        let slots =
            usize::try_from(self.pooling_maximum_instances).map_err(|_| invalid_config())?;
        let core = usize::try_from(self.pooling_maximum_core_instances_per_component)
            .map_err(|_| invalid_config())?;
        let memories = usize::try_from(self.pooling_maximum_memories_per_component)
            .map_err(|_| invalid_config())?;
        let tables = usize::try_from(self.pooling_maximum_tables_per_component)
            .map_err(|_| invalid_config())?;
        let memory = usize::try_from(self.maximum_memory_bytes).map_err(|_| invalid_config())?;
        let table = self.maximum_table_elements.checked_mul(size_of::<usize>());
        let parts = [
            Some(self.pooling_maximum_component_instance_bytes),
            self.pooling_maximum_core_instance_bytes.checked_mul(core),
            memory.checked_mul(memories),
            table.and_then(|bytes| bytes.checked_mul(tables)),
            Some(self.async_stack_bytes),
        ];
        parts
            .into_iter()
            .try_fold(0_usize, |total, part| {
                total.checked_add(part?.checked_mul(slots)?)
            })
            .ok_or_else(invalid_config)?;
        Ok(())
    }
}
