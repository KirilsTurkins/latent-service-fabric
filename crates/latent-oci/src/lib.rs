//! OCI distribution interfaces for capsules, signatures, attestations, and derived artifacts.

#![forbid(unsafe_code)]

use latent_artifacts::{ArtifactDescriptor, ArtifactLayer};
use latent_core::{BoxFuture, Metadata, PlatformError, ReleaseDigest};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciReference {
    pub registry: String,
    pub repository: String,
    pub reference: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciDescriptor {
    pub media_type: String,
    pub digest: String,
    pub size_bytes: u64,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciManifest {
    pub schema_version: u32,
    pub media_type: String,
    pub artifact_type: String,
    pub config: OciDescriptor,
    pub layers: Vec<OciDescriptor>,
    pub subject: Option<OciDescriptor>,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OciPushRequest {
    pub reference: OciReference,
    pub manifest: OciManifest,
    pub layers: Vec<(ArtifactLayer, Vec<u8>)>,
}

pub trait OciRegistry: Send + Sync {
    fn resolve<'a>(
        &'a self,
        reference: &'a OciReference,
    ) -> BoxFuture<'a, Result<Option<OciDescriptor>, PlatformError>>;

    fn pull_manifest<'a>(
        &'a self,
        reference: &'a OciReference,
    ) -> BoxFuture<'a, Result<OciManifest, PlatformError>>;

    fn pull_blob<'a>(
        &'a self,
        reference: &'a OciReference,
        digest: &'a str,
    ) -> BoxFuture<'a, Result<Vec<u8>, PlatformError>>;

    fn push<'a>(
        &'a self,
        request: OciPushRequest,
    ) -> BoxFuture<'a, Result<ReleaseDigest, PlatformError>>;

    fn list_referrers<'a>(
        &'a self,
        reference: &'a OciReference,
        artifact_type: Option<&'a str>,
    ) -> BoxFuture<'a, Result<Vec<OciDescriptor>, PlatformError>>;
}

pub trait OciArtifactMapper: Send + Sync {
    fn to_artifact_descriptor(
        &self,
        reference: &OciReference,
        manifest: &OciManifest,
    ) -> Result<ArtifactDescriptor, PlatformError>;
}
