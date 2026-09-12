//! Capsule artifact storage, retrieval, caching, verification, and derived artifacts.

#![forbid(unsafe_code)]

mod admission;
mod audit;
mod content_hash;
mod historical_execution;
mod lifecycle;
mod local_repository;
pub mod package;
mod preparation;
mod preparation_fingerprint;
mod raw_cache;
mod verification_statistics;
mod verified_metadata;

pub use audit::{
    reconcile_release_audit, AuditedAdmissionAuthority, ReleaseAuditAck, ReleaseAuditGuard,
    ReleaseAuditStatus,
};
pub use historical_execution::{
    HistoricalExecutionSnapshot, HistoricalExecutionState, HistoricalReleaseDenial,
};
pub use lifecycle::{
    LifecycleAuthorityHandle, LifecycleEligibility, LifecycleLimits, LifecycleScope,
    ManagedPublicationReceipt, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseEligibilityReason, ReleaseEvidenceUpload, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseLifecycleRecord, ReleaseLifecycleState, ReleaseLifecycleStatus,
    ReleaseLiveEligibility, ReleaseMutationContext, ReleaseOperationDisposition,
    ReleaseOperationLookup, ReleaseOperationPrecondition, ReleaseOperationPreview,
    ReleaseOperationReceipt, ReleasePolicyIdentity, ReleaseUseEligibility, ReleaseUseRecheck,
};
pub use preparation::{
    ArtifactPreparationIdentity, ArtifactPreparationReadBounds, ArtifactPreparationReadLimits,
    ArtifactPreparationSource, OwnedArtifactPreparationSource,
};
pub use preparation_fingerprint::{
    preparation_metadata_fingerprint, PreparationMetadataFingerprint,
};
pub use raw_cache::{
    RawArtifactBytes, RawArtifactCache, RawArtifactCacheLimits, RawArtifactCacheSnapshot,
    RawArtifactEviction, RawArtifactKey, RawArtifactPin, RawArtifactRead, RawArtifactReclaim,
    RawArtifactReclamation, RawArtifactWrite,
};
pub use verification_statistics::ArtifactVerificationSnapshot;
pub use verified_metadata::VerifiedArtifactMetadata;

pub use admission::{
    AdmissionAuthority, AdmissionBinding, AdmissionEvidence, AdmissionGrant, AdmissionRecheck,
    AdmissionStorageLimits, PackageAdmissionUpload, ReleaseEligibility, VerifiedAdmission,
};
pub use local_repository::contract_metadata::{
    decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
pub use local_repository::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};

/// Contract metadata accepted by artifact publication and consumed by route compilation.
pub use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{
    ArtifactReference, BoxFuture, ContractId, Metadata, PlatformError, PlatformErrorCode,
    PublisherId, ReleaseDigest, ServiceId, TenantId,
};
use latent_manifest::CapsuleManifest;
use std::sync::Arc;

/// Computes the canonical SHA-256 content identity shared by local catalogs.
#[must_use]
pub fn content_digest(bytes: &[u8]) -> ReleaseDigest {
    content_hash::release_digest(bytes)
}

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

/// Immutable metadata verified at publication or recovery, without loading component bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactCatalogEntry {
    pub descriptor: ArtifactDescriptor,
    pub tenant: Option<TenantId>,
    pub service: ServiceId,
    pub semantic_version: String,
    pub world: ContractId,
}

/// The tenant comes from the authenticated adapter, independently of the opaque cursor.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactCatalogPageRequest {
    pub tenant: TenantId,
    pub service: Option<ServiceId>,
    pub page_size: u32,
    pub page_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactCatalogPage {
    pub entries: Vec<ArtifactCatalogEntry>,
    pub next_page_token: Option<String>,
    /// Repository-local visibility generation; tokens also expire when it is reopened.
    pub catalog_generation: u64,
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
    /// Authenticated publication with a bounded durable retry receipt. The host
    /// callback must accept the exact response before any filesystem mutation.
    fn publish_managed<'a>(
        &'a self,
        _context: ReleaseMutationContext,
        _upload: ManagedPublicationUpload,
        _preflight: &'a mut (dyn for<'p> FnMut(ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<ManagedPublicationReceipt, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    fn get_release_lifecycle<'a>(
        &'a self,
        _scope: &'a LifecycleScope,
        _release: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<Option<ReleaseLifecycleStatus>, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    fn get_release_operation<'a>(
        &'a self,
        _scope: &'a LifecycleScope,
        _operation_id: &'a str,
    ) -> BoxFuture<'a, Result<ReleaseOperationLookup, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    fn change_release_lifecycle<'a>(
        &'a self,
        _context: ReleaseMutationContext,
        _release: &'a ReleaseDigest,
        _action: ReleaseLifecycleAction,
        _reason: ReleaseLifecycleReason,
        _preflight: &'a mut (dyn for<'p> FnMut(ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<ReleaseOperationReceipt, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    fn renew_release_evidence<'a>(
        &'a self,
        _context: ReleaseMutationContext,
        _release: &'a ReleaseDigest,
        _package: &'a latent_core::PackageDigest,
        _evidence: ReleaseEvidenceUpload,
        _preflight: &'a mut (dyn for<'p> FnMut(ReleaseOperationPreview<'p>) -> Result<(), PlatformError>
                     + Send),
    ) -> BoxFuture<'a, Result<ReleaseOperationReceipt, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    /// Authenticated package publication. The rejection-only callback validates
    /// the exact prospective response before staging or mutation, without locks.
    fn admit_package<'a>(
        &'a self,
        _tenant: &'a TenantId,
        _upload: PackageAdmissionUpload,
        _preflight: &'a mut (dyn FnMut(&ArtifactCatalogEntry) -> Result<(), PlatformError> + Send),
    ) -> BoxFuture<'a, Result<ArtifactCatalogEntry, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    /// Live admission currentness, independent of optional integrity stamps.
    /// None denotes an explicitly local/generic source, never signed authority.
    fn release_eligibility(
        &self,
        _release: &ReleaseDigest,
    ) -> Result<Option<ReleaseEligibility>, PlatformError> {
        Ok(None)
    }

    /// Sealed lifecycle and optional signing authority, independent of cache stamps.
    /// Missing capability is only an unmanaged embedding, never a catalog grant.
    fn execution_eligibility(
        &self,
        _release: &ReleaseDigest,
    ) -> Result<Option<ReleaseUseEligibility>, PlatformError> {
        Ok(None)
    }

    /// Historical metadata for control recovery, with an explicit permission state.
    /// The generic adapter never combines caller metadata with a delegated token.
    fn historical_execution_snapshot<'a>(
        &'a self,
        release: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<HistoricalExecutionSnapshot, PlatformError>> {
        Box::pin(async move {
            let metadata = self.fetch_verified_metadata(release).await?;
            Ok(HistoricalExecutionSnapshot::unmanaged(metadata))
        })
    }

    /// Transfers preparation reads and identity lookup to one sealed, owned
    /// source. Workers may retain it after the requesting future is dropped.
    /// Selecting this source also selects its fetch for stamp-ineligible paths;
    /// never combine its identity with this trait object's separate `fetch`.
    /// Generic implementations preserve their checked asynchronous fetch path.
    fn owned_preparation_source(self: Arc<Self>) -> Option<OwnedArtifactPreparationSource> {
        None
    }

    /// Delegates preparation identity AND full reads to one sealed repository
    /// source. Consumers selecting this capability must also use its fetch for
    /// cold and stamp-ineligible paths, never combine it with this trait's fetch.
    /// Generic implementations retain their fully checked path by returning None.
    fn preparation_source(&self) -> Option<ArtifactPreparationSource<'_>> {
        None
    }

    /// Returns None for absent, foreign-tenant and tenant-neutral releases.
    /// Implementations must authorize scope before cloning metadata and must not fetch components.
    fn get_catalog_entry<'a>(
        &'a self,
        _tenant: &'a TenantId,
        _digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<Option<ArtifactCatalogEntry>, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    /// Uses a scoped index, never a global scan followed by filtering or full artifact fetches.
    fn list_catalog_entries<'a>(
        &'a self,
        _request: &'a ArtifactCatalogPageRequest,
    ) -> BoxFuture<'a, Result<ArtifactCatalogPage, PlatformError>> {
        Box::pin(async { Err(unsupported_catalog_query()) })
    }

    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>>;

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>>;

    /// Reads metadata after verifying the component's content identity and length.
    /// The default fetches and checks the full artifact; local implementations may
    /// stream component verification without retaining its bytes. This is a fresh
    /// integrity check, not an authenticated prepared-cache lookup.
    fn fetch_verified_metadata<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<VerifiedArtifactMetadata, PlatformError>> {
        Box::pin(async move {
            let metadata = VerifiedArtifactMetadata::from_artifact(self.fetch(digest).await?)?;
            metadata.verify_requested(digest)?;
            Ok(metadata)
        })
    }

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>>;

    /// Lists releases in ascending digest order without repository downcasting.
    /// Implementations must bound both entry count and response materialization;
    /// callers may paginate with `next_after`.
    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>>;
}

fn unsupported_catalog_query() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::IncompatibleContract,
        message: "artifact-catalog-query-unsupported".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
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
