//! Bounded, negative-only retention authority. A pin is never an execution grant.

use crate::{LifecycleScope, PublicationRef, ReleaseActor};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};

pub const MAX_PUBLICATION_RETENTION_BATCH: usize = 32;
pub const MAX_PUBLICATION_RETENTION_PINS: usize = 1024;
pub const MAX_PUBLICATION_RETENTION_RECEIPTS: usize = 64;

/// An opaque, exact catalog snapshot, not authorization to inspect its contents.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct PublicationRetentionFence(pub(crate) [u8; 32]);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum PublicationRetentionAction {
    Pin,
    Unpin,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationRetentionTarget {
    pub publication: PublicationRef,
    pub expected_generation: u64,
}

/// Supplied by a trusted host adapter only after authenticating and authorizing
/// the scope/actor. Identifiers and a fence do not confer that authorization.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationRetentionRequest {
    pub scope: LifecycleScope,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub expected_catalog_fence: PublicationRetentionFence,
    pub action: PublicationRetentionAction,
    /// Strictly increasing publication IDs; duplicates and empty batches refuse.
    pub targets: Vec<PublicationRetentionTarget>,
}
impl PublicationRetentionRequest {
    pub(crate) fn validate(&self) -> Result<(), PlatformError> {
        self.scope.validate()?;
        self.actor.validate()?;
        token(&self.operation_id)?;
        if self.targets.is_empty()
            || self.targets.len() > MAX_PUBLICATION_RETENTION_BATCH
            || self.targets.capacity() > MAX_PUBLICATION_RETENTION_BATCH
            || self.operation_id.capacity() > 128
        {
            return Err(invalid());
        }
        for target in &self.targets {
            target.publication.scope.validate()?;
            if target.publication.scope != self.scope {
                return Err(unavailable_target());
            }
            if target.expected_generation == 0 {
                return Err(invalid());
            }
        }
        if self
            .targets
            .windows(2)
            .any(|pair| pair[0].publication.id >= pair[1].publication.id)
        {
            return Err(invalid());
        }
        Ok(())
    }
}

/// Persisted independently of eligibility and generation changes. Revoking,
/// retiring or renewing a publication does not silently discard this pin.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationRetentionPin {
    pub publication: PublicationRef,
    pub pinned_generation: u64,
    pub actor: ReleaseActor,
    pub operation_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationRetentionReceipt {
    pub request: PublicationRetentionRequest,
    pub revision: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PublicationRetentionLookup {
    Found(PublicationRetentionReceipt),
    /// Absence/eviction proves neither nonexecution nor permission to replay.
    Unknown,
    /// This incarnation cannot establish durability. Reopen and query the
    /// original operation identity; do not manufacture a replacement operation.
    Uncertain,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationRetentionSelection {
    pub target: PublicationRetentionTarget,
    pub pin: Option<PublicationRetentionPin>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationRetentionSnapshot {
    pub catalog_fence: PublicationRetentionFence,
    pub selections: Vec<PublicationRetentionSelection>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationRetentionResult {
    pub receipt: PublicationRetentionReceipt,
    pub replay: bool,
}

pub(crate) fn token(value: &str) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > 128
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
    {
        return Err(invalid());
    }
    Ok(())
}
pub(crate) fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
pub(crate) fn invalid() -> PlatformError {
    failure(
        PlatformErrorCode::InvalidArgument,
        "publication-retention-invalid",
    )
}
pub(crate) fn unavailable_target() -> PlatformError {
    failure(
        PlatformErrorCode::NotFound,
        "publication-retention-target-unavailable",
    )
}

/// Explicit development-only fault injection; absent from normal host builds.
#[cfg(feature = "development-test-host")]
#[derive(Debug, Clone, Copy)]
pub enum DevelopmentRetentionFault {
    AfterIntent,
    AfterHead,
    AfterIntentRemoval,
    AfterFormatPromotion,
}
