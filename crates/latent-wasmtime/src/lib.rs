//! Wasmtime Component Model preparation and execution for the Phase 0 echo spike.
//!
//! The concrete backend intentionally supports only `examples:echo/service@0.1.0`.
//! It retains a bounded node-owned cache of compiled component state, while every
//! invocation receives a fresh Wasmtime store, limiter, host context, log buffer,
//! and component instance. Epoch interruption and fuel stop non-cooperative guest
//! code without exposing WASI or ambient operating-system authority.

#![forbid(unsafe_code)]

mod backend;
mod bindings;
mod containment;
mod host;

use latent_artifacts::CapsuleArtifact;
use latent_core::{BoxFuture, Metadata, PlatformError, ReleaseDigest};
use latent_executor::{ExecutionBackend, PreparationKey, PreparedComponent};

pub use backend::{
    InvocationTimingStoreSnapshot, Phase0InstanceAllocator, Phase0InvocationTiming,
    Phase0WasmtimeBackend, Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory,
    PreparedCacheSnapshot, BACKEND_ID, CONTEXT_IMPORT, ECHO_DOMAIN_ERROR_MEDIA_TYPE, ECHO_EXPORT,
    ECHO_SUCCESS_MEDIA_TYPE, ECHO_WORLD, LOG_IMPORT, WASMTIME_VERSION,
};
pub use containment::RuntimeResourceSnapshot;
pub use host::{BoundedLogSink, CapturedLog};

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
