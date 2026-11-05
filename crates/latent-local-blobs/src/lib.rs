//! Single owner of local immutable blob custody and captured pins.
#![forbid(unsafe_code)]

use latent_core::{BlobDigest, Metadata, TenantId};

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

#[cfg(target_os = "linux")]
pub mod local;

#[cfg(target_os = "linux")]
pub mod provider;
