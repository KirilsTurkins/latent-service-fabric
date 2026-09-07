//! One configured engine and bounded runtime state per node-owned factory.

use std::sync::Arc;
use std::time::Duration;

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::{ExecutionBackend, PreparationKey};
use wasmtime::{Config, Engine};

use crate::backend::{SharedRuntime, WasmtimeBackend};
use crate::config::{DispatchMode, WasmtimeConfig};
use crate::containment::{bounded_text, platform_error, start_epoch_ticker, MAX_DIAGNOSTIC_BYTES};
use crate::{BoundedLogSink, WasmtimeEngineFactory, WasmtimeEngineProfile};

pub struct WasmtimeComponentEngineFactory {
    engine: Engine,
    config: WasmtimeConfig,
    profile: WasmtimeEngineProfile,
    shared: Arc<SharedRuntime>,
}

impl WasmtimeComponentEngineFactory {
    pub fn new(config: WasmtimeConfig) -> Result<Self, PlatformError> {
        Self::with_mode(config, DispatchMode::Generic)
    }

    pub(crate) fn with_mode(
        mut config: WasmtimeConfig,
        mode: DispatchMode,
    ) -> Result<Self, PlatformError> {
        if mode == DispatchMode::Phase0 {
            // Preserve the Phase 0 64 KiB payload plus 16 KiB canonical ABI
            // allowance. The effective value participates in preparation identity.
            config.hostcall_fuel = config.hostcall_fuel.min(80 * 1024);
        }
        config.validate()?;
        if mode == DispatchMode::Generic && !config.prepared_cache_enabled {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "cache-disabled preparation is restricted to the Phase 0 profiling facade",
                false,
            ));
        }
        let mut engine_config = Config::new();
        config.apply_engine(&mut engine_config)?;
        let shared = Arc::new(SharedRuntime::new(&config)?);
        let engine = Engine::new(&engine_config).map_err(|error| {
            platform_error(
                PlatformErrorCode::Internal,
                &format!(
                    "failed to construct Wasmtime engine: {}",
                    bounded_text(&error.to_string(), MAX_DIAGNOSTIC_BYTES)
                ),
                false,
            )
        })?;
        start_epoch_ticker(
            &engine,
            Duration::from_millis(config.epoch_tick_interval_millis),
        )?;
        let profile = config.profile(mode);
        Ok(Self {
            engine,
            config,
            profile,
            shared,
        })
    }

    #[must_use]
    pub fn profile(&self) -> &WasmtimeEngineProfile {
        &self.profile
    }

    #[must_use]
    pub fn preparation_key(&self, release: ReleaseDigest) -> PreparationKey {
        PreparationKey {
            release,
            engine_version: self.profile.wasmtime_version.clone(),
            engine_configuration_digest: self.profile.configuration["configuration-digest"].clone(),
            target_triple: self.profile.target_triple.clone(),
            cpu_feature_set: self.profile.cpu_feature_set.clone(),
        }
    }

    #[must_use]
    pub fn log_sink(&self) -> BoundedLogSink {
        self.shared.log_sink.clone()
    }

    #[must_use]
    pub fn create_backend_instance(&self) -> WasmtimeBackend {
        WasmtimeBackend::new(
            self.engine.clone(),
            self.profile.clone(),
            self.config.clone(),
            Arc::clone(&self.shared),
        )
    }
}

impl WasmtimeEngineFactory for WasmtimeComponentEngineFactory {
    fn profile(&self) -> &WasmtimeEngineProfile {
        &self.profile
    }

    fn create_backend(&self) -> Result<Box<dyn ExecutionBackend>, PlatformError> {
        Ok(Box::new(self.create_backend_instance()))
    }
}
