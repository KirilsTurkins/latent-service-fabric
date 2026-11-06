//! Large-value storage, staged writes, immutable references, and transfer interfaces.

#![forbid(unsafe_code)]

use latent_core::{ActivationId, BoxFuture, Metadata, PlatformError, TenantId};
pub use latent_local_blobs::{BlobRange, BlobReference};

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

    fn seal(
        &self,
        session: BlobWriteSession,
    ) -> BoxFuture<'_, Result<BlobReference, PlatformError>>;

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

    fn revoke(&self, lease: BlobLease) -> BoxFuture<'_, Result<(), PlatformError>>;
}

pub trait BlobTransfer: Send + Sync {
    fn ensure_local<'a>(
        &'a self,
        reference: &'a BlobReference,
    ) -> BoxFuture<'a, Result<BlobReference, PlatformError>>;
}

/// The local durable filesystem profile requires Linux descriptor-relative I/O.
#[cfg(target_os = "linux")]
pub mod local {
    pub use latent_local_blobs::local::*;

    // S3 keeps the exact same protected filesystem implementation private.
    mod model {
        pub(super) use latent_local_blobs::local::LocalBlobError;
        pub(super) type Result<T> = std::result::Result<T, LocalBlobError>;
    }
    #[path = "fs.rs"]
    pub(crate) mod fs;
}

/// Capability-governed adapter on the configured shared blocking owner.
#[cfg(target_os = "linux")]
pub use latent_local_blobs::provider;

/// Authenticated, version-pinned S3 blobs with a finite private cleanup inventory.
#[cfg(target_os = "linux")]
pub mod s3;

#[cfg(all(test, target_os = "linux"))]
mod local_facade_type_tests {
    use std::any::TypeId;

    #[test]
    fn local_facade_reexports_the_original_custody_types() {
        assert_eq!(
            include_bytes!("local/fs.rs"),
            include_bytes!("../../latent-local-blobs/src/local/fs.rs")
        );
        assert_eq!(
            TypeId::of::<crate::BlobReference>(),
            TypeId::of::<latent_local_blobs::BlobReference>()
        );
        assert_eq!(
            TypeId::of::<crate::BlobRange>(),
            TypeId::of::<latent_local_blobs::BlobRange>()
        );
        assert_eq!(
            TypeId::of::<crate::local::LocalBlobStore>(),
            TypeId::of::<latent_local_blobs::local::LocalBlobStore>()
        );
        assert_eq!(
            TypeId::of::<crate::local::LocalDurablePin>(),
            TypeId::of::<latent_local_blobs::local::LocalDurablePin>()
        );
        assert_eq!(
            TypeId::of::<crate::provider::CapturedLocalPayload>(),
            TypeId::of::<latent_local_blobs::provider::CapturedLocalPayload>()
        );
        assert_eq!(
            TypeId::of::<crate::provider::LocalBlobProvider>(),
            TypeId::of::<latent_local_blobs::provider::LocalBlobProvider>()
        );
    }
}
