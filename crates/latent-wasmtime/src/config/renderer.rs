use super::{invalid_config, CompilerOptimization, InstanceAllocator, WasmtimeConfig};
use latent_core::PlatformError;

impl WasmtimeConfig {
    /// Installs the selected engine shape without increasing source, fuel,
    /// aggregate memory, queue, cache, or payload budgets supplied by the owner.
    pub fn install_angular_renderer(&mut self) {
        self.angular_renderer = true;
        self.maximum_wasm_stack_bytes = 2 * 1024 * 1024;
        self.async_stack_bytes = 4 * 1024 * 1024;
        self.maximum_instances_per_store = 32;
        self.maximum_memories_per_store = 2;
        self.maximum_tables_per_store = 4;
        self.maximum_table_elements = 131_072;
    }

    pub(super) fn validate_renderer(&self) -> Result<(), PlatformError> {
        if self.angular_renderer
            && (self.instance_allocator != InstanceAllocator::OnDemand
                || self.compiler_optimization != CompilerOptimization::Speed
                || self.maximum_wasm_stack_bytes != 2 * 1024 * 1024
                || self.async_stack_bytes != 4 * 1024 * 1024
                || self.maximum_instances_per_store != 32
                || self.maximum_memories_per_store != 2
                || self.maximum_tables_per_store != 4
                || self.maximum_table_elements != 131_072
                || self.fuel_async_yield_interval.is_none())
        {
            return Err(invalid_config());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renderer_installation_preserves_operator_budgets_and_checks_the_selected_engine() {
        let mut config = WasmtimeConfig {
            fuel_async_yield_interval: Some(10_000),
            ..WasmtimeConfig::default()
        };
        let previous = config.clone();
        config.install_angular_renderer();
        config.validate().unwrap();
        assert_eq!(config.maximum_memory_bytes, previous.maximum_memory_bytes);
        assert_eq!(config.maximum_fuel, previous.maximum_fuel);
        assert_eq!(
            config.maximum_component_bytes,
            previous.maximum_component_bytes
        );
        assert_eq!(config.cache_limits(), previous.cache_limits());
        assert_ne!(
            config.detected_runtime_profile().unwrap(),
            previous.detected_runtime_profile().unwrap()
        );
        for mutate in [
            (|c: &mut WasmtimeConfig| c.instance_allocator = InstanceAllocator::Pooling)
                as fn(&mut WasmtimeConfig),
            |c| c.compiler_optimization = CompilerOptimization::SpeedAndSize,
            |c| c.fuel_async_yield_interval = None,
            |c| c.maximum_memories_per_store = 3,
            |c| c.maximum_table_elements += 1,
        ] {
            let mut wrong = config.clone();
            mutate(&mut wrong);
            assert!(wrong.validate().is_err());
        }
    }

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    #[test]
    fn external_renderer_keeps_enforced_admission_and_isolated_compiler_requirements() {
        use super::super::{DispatchMode, ExecutionIsolationProfile};

        let mut config = WasmtimeConfig {
            execution_isolation_profile: ExecutionIsolationProfile::ExternalCapsule,
            fuel_async_yield_interval: Some(10_000),
            ..WasmtimeConfig::default()
        };
        config.install_angular_renderer();
        config.validate().unwrap();
        for (admission, compiler) in [(false, false), (true, false), (false, true)] {
            assert!(config
                .execution_isolation_profile
                .validate_owners(DispatchMode::Generic, admission, compiler)
                .is_err());
        }
        config
            .execution_isolation_profile
            .validate_owners(DispatchMode::Generic, true, true)
            .unwrap();
        assert!(config
            .execution_isolation_profile
            .validate_owners(DispatchMode::Phase0, true, true)
            .is_err());
    }
}
