//! One configured engine and bounded runtime state per node-owned factory.

use std::sync::Arc;
use std::time::Duration;

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_executor::{ExecutionBackend, PreparationKey};
use wasmtime::{Config, Engine};

use crate::backend::{SharedRuntime, WasmtimeBackend};
use crate::config::{DispatchMode, WasmtimeConfig};
use crate::containment::{bounded_text, platform_error, EpochTicker, MAX_DIAGNOSTIC_BYTES};
use crate::{BoundedLogSink, WasmtimeEngineFactory, WasmtimeEngineProfile, WasmtimeHostServices};

pub struct WasmtimeComponentEngineFactory {
    engine: Engine,
    config: WasmtimeConfig,
    profile: WasmtimeEngineProfile,
    shared: Arc<SharedRuntime>,
}

impl WasmtimeComponentEngineFactory {
    /// Independent counters remain available after the factory is consumed.
    #[must_use]
    pub fn compiler_observer(&self) -> crate::CompilerObserver {
        self.shared
            .compiler
            .as_ref()
            .map_or_else(crate::CompilerObserver::disabled, |pool| pool.observer())
    }

    /// Closes compiler admission now, then waits for worker-owned work to end.
    /// The caller applies its own deadline and retains this owner on timeout.
    /// Successful quiescence precedes, and does not replace, final thread joins.
    pub fn quiesce_compiler(&self) -> latent_core::BoxFuture<'_, Result<(), PlatformError>> {
        self.shared.compiler.as_ref().map_or_else(
            || Box::pin(async { Ok(()) }) as latent_core::BoxFuture<'_, Result<(), PlatformError>>,
            crate::compiler::CompilerPool::quiesce,
        )
    }
    pub fn new(config: WasmtimeConfig) -> Result<Self, PlatformError> {
        Self::with_mode(config, DispatchMode::Generic)
    }

    pub fn with_host_services(
        config: WasmtimeConfig,
        services: WasmtimeHostServices,
    ) -> Result<Self, PlatformError> {
        Self::with_mode_and_services(config, DispatchMode::Generic, services)
    }

    pub(crate) fn with_mode(
        config: WasmtimeConfig,
        mode: DispatchMode,
    ) -> Result<Self, PlatformError> {
        Self::with_mode_and_services(config, mode, WasmtimeHostServices::default())
    }

    fn with_mode_and_services(
        mut config: WasmtimeConfig,
        mode: DispatchMode,
        services: WasmtimeHostServices,
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
        let epoch_ticker = EpochTicker::start(
            &engine,
            Duration::from_millis(config.epoch_tick_interval_millis),
        )?;
        let profile = config.profile(mode);
        let shared = Arc::new(SharedRuntime::new(
            &config,
            services,
            epoch_ticker,
            engine.clone(),
            profile.clone(),
        )?);
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

    /// Returns diagnostics ownership without retaining the engine or helpers.
    #[must_use]
    pub fn preparation_observer(&self) -> crate::PreparationObserver {
        self.shared.preparation_observer.clone()
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

    /// Consumes this factory and stops and joins its compiler and epoch workers
    /// once all backends and affine ready/prepared-use owners have been dropped.
    ///
    /// Returns `Unavailable` if another runtime owner remains. That owner keeps
    /// the workers owned; its final drop stops and joins them. The factory is
    /// consumed on success and failure. Joins hold no runtime lock and wake idle
    /// workers immediately; active native compilation must return before joining.
    ///
    /// Final destruction from one of its own compiler workers aborts the process:
    /// a trusted host callback must retain an external factory owner until join,
    /// because synchronous destruction cannot join its own thread.
    pub fn shutdown(self) -> Result<(), PlatformError> {
        let Self { shared, .. } = self;
        let mut shared = Arc::try_unwrap(shared).map_err(|_| {
            platform_error(
                PlatformErrorCode::Unavailable,
                "wasmtime-runtime-still-owned",
                false,
            )
        })?;
        shared.shutdown()
    }
}

#[cfg(test)]
mod tests;

impl WasmtimeEngineFactory for WasmtimeComponentEngineFactory {
    fn profile(&self) -> &WasmtimeEngineProfile {
        &self.profile
    }

    fn create_backend(&self) -> Result<Box<dyn ExecutionBackend>, PlatformError> {
        Ok(Box::new(self.create_backend_instance()))
    }
}
