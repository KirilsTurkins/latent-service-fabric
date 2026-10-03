//! Exact selected signed companion, with no caller-created declaration authority.
mod retained;

use std::sync::Arc;

use latent_core::{
    native_capacity::NativeReservation, ArtifactBlobDigest, PlatformError, PlatformErrorCode,
};
use latent_manifest::TransactionBinding;

use crate::{ReleaseUseEligibility, ReleaseUseRecheck, VerifiedArtifactMetadata};

/// These allowances belong to one actual recovery job. The producer never
/// creates a reservation or borrows the protected store's resident allowance.
pub const TRANSACTION_ASSET_WORK_BYTES: u64 = 24 * 1024 * 1024;
pub const TRANSACTION_ASSET_RESPONSE_BYTES: u64 = 2 * 1024 * 1024;
pub(crate) const DOCUMENT_BYTES: usize = 256 * 1024;
pub(crate) const COMPANION_BYTES: usize = 128 * 1024;
pub(crate) const CONTROL_METADATA_BYTES: usize = 4 * 1024 * 1024;
pub(crate) const COMPANION_MEDIA_TYPE: &str = "application/vnd.latent.transaction-binding.v1+json";
pub(crate) const COMPANION_PATH: &str = "transaction-binding.json";

pub type SelectedTransactionAssetParts = (
    VerifiedArtifactMetadata,
    TransactionBinding,
    ReleaseUseEligibility,
    ArtifactBlobDigest,
    Arc<NativeReservation>,
);

/// Private construction requires a fresh COMPLETE/streamed component/package
/// association through the exact admitted catalog selection. This value is
/// affine and travels inside its original prepaid NativeBuffer; it is not an
/// execution, policy, namespace, or readiness approval.
pub struct SelectedTransactionAsset {
    pub(crate) metadata: VerifiedArtifactMetadata,
    pub(crate) declaration: TransactionBinding,
    pub(crate) publication: ReleaseUseEligibility,
    pub(crate) asset_digest: ArtifactBlobDigest,
    pub(crate) original: Arc<NativeReservation>,
}

impl SelectedTransactionAsset {
    #[must_use]
    pub fn metadata(&self) -> &VerifiedArtifactMetadata {
        &self.metadata
    }
    #[must_use]
    pub fn declaration(&self) -> &TransactionBinding {
        &self.declaration
    }
    #[must_use]
    pub fn publication(&self) -> &ReleaseUseEligibility {
        &self.publication
    }
    #[must_use]
    pub fn asset_digest(&self) -> &ArtifactBlobDigest {
        &self.asset_digest
    }

    /// Rechecks the original job deadline/close and original selected catalog
    /// grant. The callback must be short, perform no I/O or waiting, and avoid
    /// reentry into either owner. The caller still seals actual policy/namespace
    /// permissions independently, in the established acceptance lock order.
    pub fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn ReleaseUseRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.original
            .with_live(|| self.publication.with_current(action))
            .map_err(|_| PlatformError {
                code: PlatformErrorCode::ResourceExhausted,
                message: "transaction-asset-owner".to_owned(),
                retryable: false,
                details: Vec::new(),
            })?
    }

    /// Trusted installation adapters move the original NativeBuffer permit
    /// alongside these parts and keep it until their physical destruction.
    #[must_use]
    pub fn into_parts(self) -> SelectedTransactionAssetParts {
        (
            self.metadata,
            self.declaration,
            self.publication,
            self.asset_digest,
            self.original,
        )
    }

    pub(crate) fn retained_bytes(&self) -> usize {
        retained::bytes(self)
    }
}
