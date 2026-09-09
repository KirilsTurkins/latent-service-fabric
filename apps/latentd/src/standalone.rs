//! Fixed node-owned composition for the standalone stateless runtime.

mod load;
#[cfg(all(test, target_os = "linux"))]
mod measurements;
mod observations;
#[cfg(all(test, target_os = "linux"))]
mod parity;
mod shutdown;
mod start;
pub mod transport;

use std::net::SocketAddr;
use std::sync::atomic::AtomicUsize;
use std::sync::Arc;
use std::time::Duration;

use latent_admission::LocalQuotaProvider;
use latent_core::ActivationClock;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_node::{LocalActivationManager, NodeInventory};
use latent_scheduler::{CellClass, LocalScheduler};
use latent_telemetry::{
    SharedActivationObserver, StructuredLocalSink, TelemetryHandle, TelemetryRuntime,
};
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory};
use latent_wire::invocation::{ActivationCleanupOwner, ActivationCleanupSnapshot};

pub use shutdown::ShutdownReport;

/// Runtime builder callbacks count actual node-owned runtime and blocking threads.
#[derive(Default)]
pub struct RuntimeThreads {
    pub invocation: Arc<AtomicUsize>,
    pub control: Arc<AtomicUsize>,
}

/// Retain this owner until explicit shutdown has joined its services and helpers.
pub struct StandaloneNode {
    transport: Option<transport::Transport>,
    cleanup: Option<ActivationCleanupOwner>,
    sampler: Option<load::LoadSampler>,
    telemetry_runtime: Option<TelemetryRuntime>,
    factory: Option<WasmtimeComponentEngineFactory>,
    load: Arc<load::HostLoad>,
    inventory: Arc<observations::InventorySlot>,
    manager: LocalActivationManager,
    scheduler: Arc<LocalScheduler>,
    backend: Arc<WasmtimeBackend>,
    quotas: LocalQuotaProvider,
    observer: Arc<SharedActivationObserver>,
    telemetry: TelemetryHandle,
    sink: Arc<StructuredLocalSink>,
    clock: Arc<dyn ActivationClock>,
    classes: Vec<CellClass>,
    shutdown_grace: Duration,
    cleanup_grace: Duration,
}

impl StandaloneNode {
    /// Actual bounded continuation ownership; absence is retained for older
    /// compositions used as comparison controls.
    #[must_use]
    pub fn cleanup_snapshot(&self) -> Option<ActivationCleanupSnapshot> {
        self.cleanup.as_ref().map(ActivationCleanupOwner::snapshot)
    }

    #[must_use]
    pub fn endpoint(&self) -> SocketAddr {
        self.transport
            .as_ref()
            .expect("live node transport")
            .local_addr()
    }

    pub fn inventory(&self) -> Result<NodeInventory, PlatformError> {
        self.inventory.snapshot_now()
    }

    #[must_use]
    pub fn is_running(&self) -> bool {
        self.transport
            .as_ref()
            .is_some_and(|transport| !transport.is_finished())
    }
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
