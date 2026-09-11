//! OCI distribution contracts for exact package bytes and detached evidence.
//!
//! Includes bounded, authenticated registry transport, byte identity and detached
//! evidence association. Publisher trust, guest validity and catalog admission
//! are separate policy decisions.

#![forbid(unsafe_code)]

mod http;
mod manifest;
mod upload;

pub use http::{
    HttpOciRegistry, OciPulledPackage, RegistryConfig, RegistryCredentials, RegistryLimits,
    RegistryUsage,
};
pub use manifest::OciManifestBytes;
pub use upload::OciPushRequest;

use latent_artifacts::ArtifactDescriptor;
use latent_core::{BoxFuture, Metadata, PackageDigest, PlatformError, PlatformErrorCode};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciReference {
    pub registry: String,
    pub repository: String,
    pub reference: String,
}

/// Generic registry descriptor metadata. Consumers must validate supported media
/// types, digest syntax, lengths and annotation bounds before following it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciDescriptor {
    pub media_type: String,
    pub artifact_type: Option<String>,
    pub digest: String,
    pub size_bytes: u64,
    pub annotations: Metadata,
}

pub trait OciRegistry: Send + Sync {
    fn resolve<'a>(
        &'a self,
        reference: &'a OciReference,
    ) -> BoxFuture<'a, Result<Option<OciDescriptor>, PlatformError>>;

    /// Returns exact received bytes, never a normalized or reserialized DTO.
    /// The implementation bounds streaming reads by the caller's positive limit
    /// and the profile ceiling before constructing the wrapper. A tag must be
    /// pinned to the returned immutable digest before durable use. Digest-pinned
    /// references must be checked against the received digest by the adapter.
    fn pull_manifest<'a>(
        &'a self,
        reference: &'a OciReference,
        max_document_bytes: usize,
    ) -> BoxFuture<'a, Result<OciManifestBytes, PlatformError>>;

    /// Validates the descriptor and a positive caller byte limit no larger than
    /// the package profile layer ceiling before streaming. The adapter compares
    /// actual length and digest with the descriptor, never hashing a reserialization
    /// or accepting oversized content before materialization.
    fn pull_blob<'a>(
        &'a self,
        reference: &'a OciReference,
        descriptor: &'a OciDescriptor,
        max_blob_bytes: u64,
    ) -> BoxFuture<'a, Result<Vec<u8>, PlatformError>>;

    /// Uploads exact verified config/layer bytes and the original manifest bytes.
    /// The returned registry digest must equal `request.manifest().digest()`; a
    /// successful transfer establishes neither publisher trust nor admission.
    fn push(&self, request: OciPushRequest) -> BoxFuture<'_, Result<PackageDigest, PlatformError>>;

    fn list_referrers<'a>(
        &'a self,
        reference: &'a OciReference,
        artifact_type: Option<&'a str>,
    ) -> BoxFuture<'a, Result<Vec<OciDescriptor>, PlatformError>>;
}

pub trait OciArtifactMapper: Send + Sync {
    /// Maps a fully associated package to legacy component catalog metadata.
    /// Implementations must call `package.capsule_layout()` to reject detached
    /// evidence, browser-assets and SSR kinds, then check embedded
    /// capsule/contracts consistency and enforce tenant/metadata conflict policy.
    /// Byte integrity alone does not grant trust or admission.
    fn to_artifact_descriptor(
        &self,
        package: &OciPushRequest,
    ) -> Result<ArtifactDescriptor, PlatformError>;
}

fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
