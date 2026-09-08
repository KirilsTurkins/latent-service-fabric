//! Versioned standalone configuration, validated before opening node resources.

mod derive;
mod input;
mod model;
mod policy;
mod runtime;
#[cfg(test)]
mod tests;
mod validation;

use std::path::{Path, PathBuf};
use std::time::Duration;

use latent_core::{PlatformError, PlatformErrorCode};

pub use model::{
    CacheConfig, CatalogConfig, CellConfig, CredentialConfig, CredentialRole, ExecutionConfig,
    LimitConfig, NodeConfig, RetentionConfig, TelemetryConfig, WorkerConfig,
};

/// Opaque, mutually compatible node settings produced by [`NodeConfig::derive`].
/// Configure the input before derivation; callers cannot alter the validated
/// plan passed to startup. This type intentionally has no `Debug` implementation
/// because its transport configuration contains credentials.
pub struct NodeSettings {
    pub(crate) data_directory: PathBuf,
    pub(crate) node: latent_node::NodeDescriptor,
    pub(crate) runtime_workers: usize,
    pub(crate) control_workers: usize,
    pub(crate) artifacts: latent_artifacts::DirectoryArtifactRepositoryConfig,
    pub(crate) deployments: latent_control_store::DirectoryDeploymentRepositoryConfig,
    pub(crate) admission: latent_admission::NodeAdmissionPolicy,
    pub(crate) scheduler: latent_scheduler::LocalSchedulerConfig,
    pub(crate) wasmtime: latent_wasmtime::WasmtimeConfig,
    pub(crate) manager: latent_node::LocalActivationManagerConfig,
    pub(crate) invocation: latent_wire::invocation::InvocationLimits,
    pub(crate) management: latent_wire::management::ManagementLimits,
    pub(crate) telemetry: latent_telemetry::TelemetryPipelineConfig,
    pub(crate) local_sink: latent_telemetry::LocalSinkConfig,
    pub(crate) observer: latent_telemetry::SharedActivationObserverConfig,
    pub(crate) inventory: latent_node::StandaloneInventoryConfig,
    pub(crate) transport: crate::standalone::transport::TransportConfig,
    pub(crate) shutdown_grace: Duration,
    pub(crate) load_sample_interval: Duration,
}

impl NodeSettings {
    /// Fixed invocation/network runtime worker count for the embedding owner.
    #[must_use]
    pub const fn runtime_workers(&self) -> usize {
        self.runtime_workers
    }

    /// Fixed control runtime worker count for the embedding owner.
    #[must_use]
    pub const fn control_workers(&self) -> usize {
        self.control_workers
    }

    /// Configured bounded drain and outer runtime shutdown interval.
    #[must_use]
    pub const fn shutdown_grace(&self) -> Duration {
        self.shutdown_grace
    }
}

impl NodeConfig {
    /// Reads at most 64 KiB plus an overflow sentinel. Relative data directories
    /// are anchored to the configuration file's absolute parent exactly once.
    pub fn load(path: &Path) -> Result<Self, PlatformError> {
        input::load(path)
    }

    /// Validates settings without creating directories, listeners, or workers.
    pub fn derive(&self) -> Result<NodeSettings, PlatformError> {
        derive::settings(self)
    }
}

const KIB: usize = 1024;
const MIB: usize = 1024 * KIB;
const IDENTIFIER_BYTES: usize = 512;
const CONTEXT_BYTES: usize = MIB;
const JOURNAL_RECORD_BYTES: usize = 4 * MIB;
const LOAD_MAXIMUM_AGE: Duration = Duration::from_secs(2);
const TRUST_CLASS: &str = "internal";

fn invalid(field: &'static str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: format!("invalid standalone configuration: {field}"),
        retryable: false,
        details: Vec::new(),
    }
}
