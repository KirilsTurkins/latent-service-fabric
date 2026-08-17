//! Large-value storage, staged writes, immutable references, and transfer interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BlobDigest, BoxFuture, Metadata, PlatformError, TenantId,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlobReference {
    pub digest: BlobDigest,
    pub size_bytes: u64,
    pub media_type: String,
    pub tenant: TenantId,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlobRange {
    pub offset: u64,
    pub length: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlobWriteSession {
    pub id: String,
    pub activation_id: ActivationId,
    pub tenant: TenantId,
    pub media_type: String,
    pub expected_size_bytes: Option<u64>,
    pub expires_at_unix_millis: u64,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlobLease {
    pub id: String,
    pub reference: BlobReference,
    pub activation_id: ActivationId,
    pub operations: Vec<String>,
    pub expires_at_unix_millis: u64,
}

pub trait BlobStore: Send + Sync {
    fn begin_write<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        media_type: &'a str,
        expected_size_bytes: Option<u64>,
    ) -> BoxFuture<'a, Result<BlobWriteSession, PlatformError>>;

    fn write<'a>(
        &'a self,
        session: &'a BlobWriteSession,
        offset: u64,
        bytes: Vec<u8>,
    ) -> BoxFuture<'a, Result<u64, PlatformError>>;

    fn seal<'a>(
        &'a self,
        session: BlobWriteSession,
    ) -> BoxFuture<'a, Result<BlobReference, PlatformError>>;

    fn read<'a>(
        &'a self,
        reference: &'a BlobReference,
        range: BlobRange,
    ) -> BoxFuture<'a, Result<Vec<u8>, PlatformError>>;

    fn delete<'a>(
        &'a self,
        reference: &'a BlobReference,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait BlobLeaseManager: Send + Sync {
    fn grant<'a>(
        &'a self,
        reference: &'a BlobReference,
        activation_id: &'a ActivationId,
        operations: &'a [String],
        ttl_millis: u64,
    ) -> BoxFuture<'a, Result<BlobLease, PlatformError>>;

    fn revoke<'a>(&'a self, lease: BlobLease) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait BlobTransfer: Send + Sync {
    fn ensure_local<'a>(
        &'a self,
        reference: &'a BlobReference,
    ) -> BoxFuture<'a, Result<BlobReference, PlatformError>>;
}
