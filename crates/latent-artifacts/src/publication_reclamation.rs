//! Bounded content observation and explicit durable publication payload reclamation.
//! A read-only assessment never substitutes for the native commit/recovery protocol.
use crate::{PublicationDeletionRequest, PublicationRetentionFence};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};

/// Maximum publication-file and canonical-blob observations in one assessment.
pub const MAX_PUBLICATION_RECLAMATION_FILES: usize = 1024;
/// Maximum bytes hashed across publication files and canonical blobs together.
pub const MAX_PUBLICATION_RECLAMATION_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationReclamationLimits {
    /// Includes repeated publication links and each distinct canonical blob.
    pub maximum_files: usize,
    /// Counts both sides of a hard link; this is work, not physical disk usage.
    pub maximum_bytes_hashed: u64,
}
impl Default for PublicationReclamationLimits {
    fn default() -> Self {
        Self {
            maximum_files: MAX_PUBLICATION_RECLAMATION_FILES,
            maximum_bytes_hashed: 64 * 1024 * 1024,
        }
    }
}
impl PublicationReclamationLimits {
    pub(crate) fn validate(self) -> Result<(), PlatformError> {
        if self.maximum_files == 0
            || self.maximum_files > MAX_PUBLICATION_RECLAMATION_FILES
            || self.maximum_bytes_hashed == 0
            || self.maximum_bytes_hashed > MAX_PUBLICATION_RECLAMATION_BYTES
        {
            return Err(crate::publication_retention::failure(
                PlatformErrorCode::InvalidArgument,
                "publication-reclamation-invalid-limits",
            ));
        }
        Ok(())
    }
}

/// Potential namespace/accounting changes, NOT a deletion receipt or a claim of
/// physical blocks freed. Independent lifecycle, evidence-revision, audit and retention
/// control files are outside these totals and remain protected.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationReclamationContent {
    pub publications: usize,
    pub publication_files: usize,
    pub publication_file_bytes: u64,
    pub selected_blobs: usize,
    pub last_reference_blobs: usize,
    pub last_reference_blob_bytes: u64,
    pub shared_blobs_retained: usize,
    pub shared_blob_bytes_retained: u64,
    /// Verified bytes per pass. Fresh mutation verifies twice within its total limit.
    pub bytes_hashed: u64,
}

/// Exact original-operation selection observed under the live native reader and
/// reference owners. A later operation must revalidate all authority and content.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationReclamationAssessment {
    pub deletion: PublicationDeletionRequest,
    /// Current observation fence, not the earlier deletion request's fence.
    pub catalog_fence: PublicationRetentionFence,
    pub reference_revision: u64,
    pub content: PublicationReclamationContent,
}

/// Continue one exact retained deletion, with a fresh observation fence.
/// The trusted host must authenticate scope/actor and reserve finite audit space.
/// `reclaim_tombstoned_publications` supports capsule and componentless-web payloads;
/// the capsule-only entry point retains its stricter target restriction.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationReclamationRequest {
    pub deletion: PublicationDeletionRequest,
    pub expected_catalog_fence: PublicationRetentionFence,
    pub limits: PublicationReclamationLimits,
}
impl PublicationReclamationRequest {
    pub(crate) fn validate(&self) -> Result<(), PlatformError> {
        self.deletion.validate()?;
        self.limits.validate()
    }
}

/// Confirmed namespace removal and accounting refund, not physical allocated
/// blocks. Lifecycle/evidence, retention pins and administrative audit are NOT
/// pruned by this operation. The original logical deletion receipt is unchanged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationReclamationReceipt {
    pub request: PublicationReclamationRequest,
    pub reference_revision: u64,
    pub content: PublicationReclamationContent,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationReclamationResult {
    pub receipt: PublicationReclamationReceipt,
    pub replay: bool,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PublicationReclamationLookup {
    Found(PublicationReclamationReceipt),
    Unknown,
    Uncertain,
}
