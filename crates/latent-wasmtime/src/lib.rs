//! Bounded generic Wasmtime Component Model execution with fresh stores.
//! A compatibility facade retains the Phase 0 echo payload contract.

#![forbid(unsafe_code)]

mod backend;
mod bindings;
mod cache;
mod config;
mod containment;
mod factory;
mod host;
mod phase0;
mod preparation_metadata;
mod services;
mod surface;
mod telemetry;
mod timing;
mod values;

use latent_artifacts::CapsuleArtifact;
use latent_core::{BoxFuture, Metadata, PlatformError, ReleaseDigest};
use latent_executor::{ExecutionBackend, PreparationKey, PreparedComponent};

pub use backend::{PreparationActivitySnapshot, WasmtimeBackend};
pub use cache::PreparedCacheSnapshot;
pub use config::{
    InstanceAllocator, Phase0InstanceAllocator, Phase0WasmtimeConfig, WasmtimeConfig,
    GENERIC_BACKEND_ID, WASMTIME_VERSION,
};
pub use containment::RuntimeResourceSnapshot;
pub use factory::WasmtimeComponentEngineFactory;
pub use host::policy::ContextExposurePolicy;
pub use host::{BoundedLogSink, CapturedLog, LogSinkError, StructuredLogSink};
pub use phase0::{
    Phase0WasmtimeBackend, Phase0WasmtimeEngineFactory, BACKEND_ID, ECHO_DOMAIN_ERROR_MEDIA_TYPE,
    ECHO_EXPORT, ECHO_SUCCESS_MEDIA_TYPE, ECHO_WORLD,
};
pub use services::WasmtimeHostServices;
pub use surface::{CONTEXT_IMPORT, LOG_IMPORT, MONOTONIC_CLOCK_IMPORT, WALL_CLOCK_IMPORT};
pub use telemetry::TelemetryLogSink;
pub use timing::{InvocationTimingStoreSnapshot, Phase0InvocationTiming};
pub use values::{ValueCodecLimits, MEDIA_TYPE as WIT_VALUES_MEDIA_TYPE};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WasmtimeEngineProfile {
    pub id: String,
    pub wasmtime_version: String,
    pub target_triple: String,
    pub cpu_feature_set: String,
    pub pooling_allocator: bool,
    pub copy_on_write_images: bool,
    pub async_support: bool,
    pub fuel_enabled: bool,
    pub epoch_interruption_enabled: bool,
    pub configuration: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AheadOfTimeArtifact {
    pub key: PreparationKey,
    pub release: ReleaseDigest,
    pub bytes: Vec<u8>,
    pub generated_at_unix_millis: u64,
    pub compiler_identity: String,
    pub metadata: Metadata,
}

pub trait WasmtimeEngineFactory: Send + Sync {
    fn profile(&self) -> &WasmtimeEngineProfile;
    fn create_backend(&self) -> Result<Box<dyn ExecutionBackend>, PlatformError>;
}

pub trait AheadOfTimeCompiler: Send + Sync {
    fn compile<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        profile: &'a WasmtimeEngineProfile,
    ) -> BoxFuture<'a, Result<AheadOfTimeArtifact, PlatformError>>;
}

pub trait AheadOfTimeCache: Send + Sync {
    fn get<'a>(
        &'a self,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<Option<AheadOfTimeArtifact>, PlatformError>>;

    fn put<'a>(&'a self, artifact: AheadOfTimeArtifact)
        -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait PrecompiledArtifactValidator: Send + Sync {
    fn validate(
        &self,
        artifact: &AheadOfTimeArtifact,
        profile: &WasmtimeEngineProfile,
    ) -> Result<PreparedComponent, PlatformError>;
}
