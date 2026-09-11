use crate::error;
use latent_artifacts::package::{package_digest, PackageLimits};
use latent_core::{PackageDigest, PlatformError, PlatformErrorCode};
use std::fmt;

/// Owned exact manifest bytes with a bounded retained length and exact digest.
/// Construction does not parse JSON or validate OCI shape, signatures or trust.
#[derive(Clone, PartialEq, Eq)]
pub struct OciManifestBytes {
    bytes: Box<[u8]>,
    digest: PackageDigest,
}

impl OciManifestBytes {
    /// Enforces a positive caller limit no larger than the package profile's
    /// 256 KiB ceiling. The transport must bound streaming reads BEFORE it
    /// materializes this Vec; this constructor cannot undo an earlier allocation.
    /// Spare input capacity is discarded rather than retained behind the bound.
    pub fn new(bytes: Vec<u8>, max_document_bytes: usize) -> Result<Self, PlatformError> {
        if max_document_bytes == 0
            || max_document_bytes > PackageLimits::default().max_document_bytes
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-oci-manifest-limit",
            ));
        }
        if bytes.len() > max_document_bytes {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "oci-manifest-byte-limit",
            ));
        }
        let digest = package_digest(&bytes);
        Ok(Self {
            bytes: bytes.into_boxed_slice(),
            digest,
        })
    }

    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub fn digest(&self) -> &PackageDigest {
        &self.digest
    }

    #[must_use]
    pub fn into_bytes(self) -> Vec<u8> {
        self.bytes.into_vec()
    }
}

impl fmt::Debug for OciManifestBytes {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OciManifestBytes")
            .field("digest", &self.digest)
            .field("size_bytes", &self.bytes.len())
            .finish()
    }
}
