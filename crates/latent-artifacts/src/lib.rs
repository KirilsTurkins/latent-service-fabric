//! Capsule artifact storage, retrieval, caching, verification, and derived artifacts.

#![forbid(unsafe_code)]

mod local_repository;

pub use local_repository::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};

use latent_contracts::ContractDescriptor;
use latent_core::{
    ArtifactReference, BoxFuture, Metadata, PlatformError, PublisherId, ReleaseDigest,
};
use latent_manifest::CapsuleManifest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactLayer {
    pub media_type: String,
    pub digest: String,
    pub size_bytes: u64,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactDescriptor {
    pub reference: ArtifactReference,
    pub release_digest: ReleaseDigest,
    pub media_type: String,
    pub size_bytes: u64,
    pub publisher: Option<PublisherId>,
    pub layers: Vec<ArtifactLayer>,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapsuleArtifact {
    pub descriptor: ArtifactDescriptor,
    pub manifest: CapsuleManifest,
    pub contracts: Vec<ContractDescriptor>,
    pub component_bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactQuery {
    pub reference: Option<ArtifactReference>,
    pub release_digest: Option<ReleaseDigest>,
    pub media_type: Option<String>,
}

/// One deterministic, bounded page from an artifact repository.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactPage {
    pub entries: Vec<ArtifactDescriptor>,
    /// Digest to pass as `after` to retrieve the next page.
    pub next_after: Option<ReleaseDigest>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CacheTier {
    Metadata,
    RawArtifact,
    AheadOfTime,
    MemoryMappedCode,
    ImportsPrepared,
    Snapshot,
    Fused,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheEntryDescriptor {
    pub key: String,
    pub release_digest: ReleaseDigest,
    pub tier: CacheTier,
    pub size_bytes: u64,
    pub last_access_unix_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DerivedArtifactDescriptor {
    pub digest: ReleaseDigest,
    pub inputs: Vec<ReleaseDigest>,
    pub policy_digest: String,
    pub compiler_digest: String,
    pub media_type: String,
}

pub trait ArtifactRepository: Send + Sync {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>>;

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>>;

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>>;

    /// Lists releases in ascending digest order without repository downcasting.
    /// Implementations must bound `limit`; callers may paginate with `next_after`.
    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>>;
}

pub trait ArtifactCache: Send + Sync {
    fn lookup<'a>(
        &'a self,
        key: &'a str,
        tier: CacheTier,
    ) -> BoxFuture<'a, Result<Option<CacheEntryDescriptor>, PlatformError>>;

    fn store<'a>(
        &'a self,
        entry: CacheEntryDescriptor,
        bytes: Vec<u8>,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn evict<'a>(&'a self, key: &'a str) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait ArtifactVerifier: Send + Sync {
    fn verify<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait DerivedArtifactRepository: Send + Sync {
    fn resolve<'a>(
        &'a self,
        descriptor: &'a DerivedArtifactDescriptor,
    ) -> BoxFuture<'a, Result<Option<Vec<u8>>, PlatformError>>;

    fn publish<'a>(
        &'a self,
        descriptor: DerivedArtifactDescriptor,
        bytes: Vec<u8>,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}
