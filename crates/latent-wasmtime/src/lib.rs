//! Wasmtime-specific preparation and execution seam definitions.

#![forbid(unsafe_code)]

use latent_artifacts::CapsuleArtifact;
use latent_core::{BoxFuture, Metadata, PlatformError, ReleaseDigest};
use latent_executor::{ExecutionBackend, PreparationKey, PreparedComponent};

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

    fn put<'a>(
        &'a self,
        artifact: AheadOfTimeArtifact,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait PrecompiledArtifactValidator: Send + Sync {
    fn validate(
        &self,
        artifact: &AheadOfTimeArtifact,
        profile: &WasmtimeEngineProfile,
    ) -> Result<PreparedComponent, PlatformError>;
}
