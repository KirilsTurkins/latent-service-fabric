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
    java_guest: bool,
    #[serde(default, skip_serializing_if = "is_false")]
    activation_import_cancellation: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    native_thread_profile: Option<NativeThreadProfile>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
enum NativeThreadProfile {
    #[serde(rename = "rust-context40-sole-consumer-one-task-start-v1")]
    RustContext40SoleConsumerOneTaskStartV1,
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
            java_guest: config.java_guest,
            activation_import_cancellation: config.activation_runtime.is_some(),
            native_thread_profile: config
                .owned_native_threads
                .then_some(NativeThreadProfile::RustContext40SoleConsumerOneTaskStartV1),
        }
    }
    pub(crate) fn validate_compiler(&self) -> Result<(), PlatformError> {
        if self.maximum_wasm_stack_bytes == 0
            || self.maximum_wasm_stack_bytes > 64 * 1024 * 1024
            || self.async_stack_bytes < self.maximum_wasm_stack_bytes
            || self.async_stack_bytes > 128 * 1024 * 1024
            || !self.memory.compiler_bounded()
            || (self.owned_native_threads()
                && (!self.activation_import_cancellation || self.java_guest))
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
        engine_config.wasm_component_model_more_async_builtins(self.activation_import_cancellation);
        // The explicit profile authenticates each final component before any
        // compile/load, including disposable compiler workers and cache reuse.
        engine_config.wasm_component_model_threading(self.owned_native_threads());
        engine_config.wasm_component_model_async_stackful(self.owned_native_threads());
        // Security upgrades must not admit new, unqualified value shapes.
        engine_config.wasm_component_model_fixed_length_lists(false);
        // Preserve the ordinary profile's pre-Java typed function references.
        // Compiling GC support into the host must not enable Wasm GC or default
        // exceptions; the Java exception profile keeps typed references disabled.
        engine_config.wasm_gc(false);
        engine_config.wasm_function_references(!self.java_guest);
        engine_config.wasm_exceptions(self.java_guest);
        engine_config.gc_support(self.java_guest);
        if self.java_guest {
            engine_config
                .gc_heap_initial_size(super::java::JAVA_EXCEPTION_HEAP_INITIAL_BYTES)
                .gc_heap_reservation(super::JAVA_EXCEPTION_HEAP_BYTES as u64)
                .gc_heap_reservation_for_growth(0)
                .gc_heap_guard_size(0)
                .gc_heap_may_move(false);
        }
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

    pub(crate) fn owned_native_threads(&self) -> bool {
        self.native_thread_profile.is_some()
    }
}

fn is_false(value: &bool) -> bool {
    !value
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closed_native_profile_and_required_settings_validate_before_engine_allocation() {
        let default = CompilerEngineSettings::from_config(&WasmtimeConfig::default());
        let mut document = serde_json::to_value(&default).unwrap();
        assert!(document.get("nativeThreadProfile").is_none());
        assert!(!default.owned_native_threads());
        document["nativeThreadProfile"] = "unknown-or-legacy".into();
        assert!(serde_json::from_value::<CompilerEngineSettings>(document.clone()).is_err());
        document["nativeThreadProfile"] = crate::component_threading::PROFILE.into();
        let unsupported: CompilerEngineSettings = serde_json::from_value(document.clone()).unwrap();
        assert!(unsupported.validate_compiler().is_err());
        document["activationImportCancellation"] = true.into();
        let selected: CompilerEngineSettings = serde_json::from_value(document.clone()).unwrap();
        selected.validate_compiler().unwrap();
        assert!(selected.owned_native_threads());
        document["javaGuest"] = true.into();
        assert!(serde_json::from_value::<CompilerEngineSettings>(document)
            .unwrap()
            .validate_compiler()
            .is_err());
    }
}

impl WasmtimeConfig {
    pub(crate) fn apply_engine(&self, engine_config: &mut Config) -> Result<(), PlatformError> {
        self.validate()?;
        CompilerEngineSettings::from_config(self).apply(engine_config);
        if self.owned_native_stacks {
            engine_config.with_host_stack(std::sync::Arc::new(crate::native_stacks::Creator));
        }
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
