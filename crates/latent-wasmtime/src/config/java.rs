//! Closed Java exception profile; the Java collector itself uses linear memory.
use latent_core::PlatformError;

use super::{invalid_config, InstanceAllocator, WasmtimeConfig};

pub(crate) const JAVA_EXCEPTION_HEAP_BYTES: usize = 4 * 1024 * 1024;
pub(super) const JAVA_EXCEPTION_HEAP_INITIAL_BYTES: u64 = 64 * 1024;

impl WasmtimeConfig {
    /// Installs engine support without increasing any operator resource budget.
    pub fn install_java_guest(&mut self) {
        self.java_guest = true;
    }

    pub(super) fn validate_java(&self) -> Result<(), PlatformError> {
        if self.java_guest
            && (self.instance_allocator != InstanceAllocator::OnDemand
                || self.angular_renderer
                || self.maximum_memory_bytes <= JAVA_EXCEPTION_HEAP_BYTES as u64
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
    use crate::config::DispatchMode;
    use wasmtime::{Config, Engine};

    #[test]
    fn java_exception_profile_is_explicit_fixed_and_cache_distinct() {
        let mut policy = WasmtimeConfig {
            fuel_async_yield_interval: Some(10_000),
            ..WasmtimeConfig::default()
        };
        let before = policy.clone();
        policy.install_java_guest();
        policy.validate().unwrap();
        assert_eq!(policy.maximum_memory_bytes, before.maximum_memory_bytes);
        assert_eq!(policy.maximum_fuel, before.maximum_fuel);
        assert_eq!(policy.cache_limits(), before.cache_limits());
        assert_ne!(
            policy.configuration_digest(DispatchMode::Generic),
            before.configuration_digest(DispatchMode::Generic)
        );
        let mut config = Config::new();
        policy.apply_engine(&mut config).unwrap();
        let engine = Engine::new(&config).unwrap();
        assert_eq!(
            engine.get_gc_heap_reservation(),
            JAVA_EXCEPTION_HEAP_BYTES as u64
        );
        assert_eq!(
            engine.get_gc_heap_initial_size(),
            JAVA_EXCEPTION_HEAP_INITIAL_BYTES
        );
        assert_eq!(engine.get_gc_heap_reservation_for_growth(), 0);
        assert!(!engine.get_gc_heap_may_move());
        assert!(engine.get_consume_fuel() && engine.get_epoch_interruption());
        for mutate in [
            (|c: &mut WasmtimeConfig| c.instance_allocator = InstanceAllocator::Pooling)
                as fn(&mut WasmtimeConfig),
            |c| c.angular_renderer = true,
            |c| c.maximum_memory_bytes = JAVA_EXCEPTION_HEAP_BYTES as u64,
            |c| c.fuel_async_yield_interval = None,
        ] {
            let mut wrong = policy.clone();
            mutate(&mut wrong);
            assert!(wrong.validate().is_err());
        }
    }
}
