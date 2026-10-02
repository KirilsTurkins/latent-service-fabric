//! Finite whole-unit recovery review on the original worker-borrowed view.
//! This module opens no engine or path, issues no permission, and cannot prove
//! physical quiescence, provider nonexecution, restore acceptance or resume.

mod artifacts;
mod inventory;
mod reconciliation;
mod restore;
pub use reconciliation::{
    ReconciliationCursor, RestoreEffectFact, RestoreEffectPage, RestoreEffectReview,
    RestoreReconciliationCounts, RestoreReconciliationPlan,
};
pub use restore::{review_restore_input, RestoreInputRequest, ReviewedRestoreInput};
#[cfg(test)]
mod tests;

use crate::atomic::{self, AtomicError, SourceIdentity};
use latent_effects::{
    authority::{DispatchProfile, EffectScope},
    dispatch_store::DispatchCatalog,
};
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    recovery::{
        snapshot::{SnapshotClosure, SnapshotError, SnapshotMetadata},
        RecoveryGuard,
    },
    store_identity::StoreIdentity,
    tenant::{self, GlobalMetadataAllowance, TenantCensus, TenantCensusReport, TenantQuota},
};
use std::time::Instant;

pub use artifacts::{original_inbox_profile_identity, original_profile_identity};
use inventory::Inventory;

/// Supplied by the trusted node installation, not inferred from namespace
/// ceilings or a transport's tenant selector. The same original deadline and
/// whole-unit authenticated read/audit decision remain independently required.
#[derive(Clone, Copy)]
pub struct RecoveryReviewRequest<'a> {
    pub quotas: &'a [TenantQuota],
    pub global_allowance: GlobalMetadataAllowance,
    pub metadata: &'a SnapshotMetadata,
    pub deadline: Instant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecoveryReviewError {
    /// Actual selected-store codec/link/counter or physical read failure.
    Source(StoreError),
    /// Installed artifact/decoder/current-access refusal; the source stays healthy.
    Review(StoreError),
    Deadline,
    Capacity,
}

impl RecoveryReviewError {
    #[must_use]
    pub const fn into_snapshot_error(self) -> SnapshotError {
        match self {
            Self::Source(error) => SnapshotError::Source(error),
            Self::Review(error) => SnapshotError::Review(error),
            Self::Deadline => SnapshotError::Deadline,
            Self::Capacity => SnapshotError::Capacity,
        }
    }
}

/// Exact immutable artifacts checked by installed owners. Neither digest
/// represents current policy or permission to send through an old endpoint.
#[derive(Debug, Clone, Copy)]
pub struct OriginalProfileArtifacts {
    pub adapter_digest: [u8; 32],
    pub definition_digest: [u8; 32],
}

/// Installed immutable catalog/decoder owners. These callbacks must compare the
/// complete original association with actual retained evidence. They may not
/// substitute the latest publication, new binding, new consumer, or bare config.
/// They perform no guest/provider operation or permission renewal. All returned
/// identities/digests remain descriptive and require separate present authority.
pub trait RecoveryReviewOwners {
    fn require_runtime(&mut self, actual_runtime_digest: [u8; 32]) -> Result<(), StoreError>;
    fn require_decoder(
        &mut self,
        format: &latent_state::namespace::compatibility::RetainedFormat,
    ) -> Result<(), StoreError>;
    fn publication(&mut self, original: &SourceIdentity) -> Result<[u8; 32], StoreError>;
    fn dispatch_profile(
        &mut self,
        original_scope: &EffectScope,
        original_profile: &DispatchProfile,
    ) -> Result<OriginalProfileArtifacts, StoreError>;
    fn inbox_profile(
        &mut self,
        original_key: &latent_core::transaction_contract::CommandKey,
        original_source: &SourceIdentity,
        original: &atomic::InboxIdentity,
    ) -> Result<[u8; 32], StoreError>;
}

/// Observed producer-owned source controls. Restore must ask their ORIGINAL
/// destination owners to establish fresh identity/epochs/checkpoint and current
/// quotas; these fields never authorize copying a source floor or reopening work.
#[derive(Debug)]
pub struct SourceControls {
    store_identity: StoreIdentity,
    dispatcher_checkpoint: Option<(u64, u64)>,
    recovery_guard: Option<RecoveryGuard>,
}
impl SourceControls {
    #[must_use]
    pub fn store_identity(&self) -> &StoreIdentity {
        &self.store_identity
    }
    #[must_use]
    pub const fn dispatcher_checkpoint(&self) -> Option<(u64, u64)> {
        self.dispatcher_checkpoint
    }
    #[must_use]
    pub fn recovery_guard(&self) -> Option<&RecoveryGuard> {
        self.recovery_guard.as_ref()
    }
}

/// Completed descriptive review of one exact borrowed native view. This value
/// retains no engine, native view, authority, provider, response body or thread.
pub struct RecoveryReview {
    view_identity: usize,
    census: TenantCensusReport,
    controls: SourceControls,
    closure: SnapshotClosure,
}
impl RecoveryReview {
    #[must_use]
    pub const fn view_identity(&self) -> usize {
        self.view_identity
    }
    #[must_use]
    pub const fn census(&self) -> TenantCensusReport {
        self.census
    }
    #[must_use]
    pub fn source_controls(&self) -> &SourceControls {
        &self.controls
    }
    #[must_use]
    pub fn closure(&self) -> &SnapshotClosure {
        &self.closure
    }
    #[must_use]
    pub fn into_snapshot_closure(self) -> SnapshotClosure {
        self.closure
    }
}

/// Compose the actual command/dispatcher/state owners on the SAME view supplied
/// by `ProtectedStoreOwner`'s exclusive Recovery custody. The caller must retain
/// its original global native reservation, deadline, authenticated whole-unit
/// access and critical audit owner through artifact review, export and readback.
/// No metadata tenant filters the unit or grants access to a foreign tenant.
pub fn review_snapshot(
    view: &ReadView,
    request: RecoveryReviewRequest<'_>,
    owners: &mut impl RecoveryReviewOwners,
    mut current: impl FnMut() -> Result<(), StoreError>,
) -> Result<RecoveryReview, RecoveryReviewError> {
    checkpoint(request.deadline, &mut current)?;
    request
        .metadata
        .validate()
        .map_err(RecoveryReviewError::Review)?;
    owners
        .require_runtime(request.metadata.runtime_digest)
        .map_err(RecoveryReviewError::Review)?;
    checkpoint(request.deadline, &mut current)?;
    let mut census = TenantCensus::capture(
        view,
        request.quotas,
        request.global_allowance,
        request.deadline,
    )
    .map_err(source)?;
    let controls = SourceControls {
        store_identity: StoreIdentity::inspect(view)
            .map_err(source)?
            .ok_or(RecoveryReviewError::Review(StoreError::UnsupportedFormat))?,
        dispatcher_checkpoint: DispatchCatalog::owner_checkpoint(view).map_err(source)?,
        // Descriptive paused history is inspectable; require_ready would erase
        // the distinction between review-required and actual engine failure.
        recovery_guard: RecoveryGuard::capture(view).map_err(source)?,
    };
    DispatchCatalog::validate_view(view).map_err(source)?;
    checkpoint(request.deadline, &mut current)?;
    let mut inventory = Inventory::default();
    let mut observed_failure = None;
    let walked = atomic::validate_view_observed(
        view,
        |view, key, bytes| contribution(view, key, bytes).map(|_| ()),
        |view, key, bytes| {
            let result = (|| {
                checkpoint(request.deadline, &mut current)?;
                let contribution = contribution(view, key, bytes).map_err(source)?;
                census
                    .observe(key, bytes, contribution)
                    .map_err(census_error)?;
                inventory.observe(view, key, bytes, owners)?;
                checkpoint(request.deadline, &mut current)
            })();
            match result {
                Ok(()) => Ok(()),
                Err(error) => {
                    // Keep healthy review/deadline refusal separate from the
                    // selected store's actual physical/codec error channel.
                    observed_failure = Some(error);
                    Err(StoreError::Invalid)
                }
            }
        },
    );
    if let Some(error) = observed_failure {
        return Err(error);
    }
    walked.map_err(source)?;
    checkpoint(request.deadline, &mut current)?;
    let census = census.finish().map_err(census_error)?;
    for format in inventory.formats().entries().keys() {
        checkpoint(request.deadline, &mut current)?;
        owners
            .require_decoder(format)
            .map_err(RecoveryReviewError::Review)?;
    }
    let closure = inventory.finish();
    closure
        .require_declared(request.metadata)
        .map_err(RecoveryReviewError::Review)?;
    checkpoint(request.deadline, &mut current)?;
    Ok(RecoveryReview {
        view_identity: view.identity(),
        census,
        controls,
        closure,
    })
}

fn checkpoint(
    deadline: Instant,
    current: &mut impl FnMut() -> Result<(), StoreError>,
) -> Result<(), RecoveryReviewError> {
    if Instant::now() >= deadline {
        return Err(RecoveryReviewError::Deadline);
    }
    current().map_err(RecoveryReviewError::Review)
}

fn source(error: StoreError) -> RecoveryReviewError {
    match error {
        StoreError::Capacity => RecoveryReviewError::Capacity,
        StoreError::SnapshotExpired => RecoveryReviewError::Deadline,
        StoreError::Invalid | StoreError::Conflict | StoreError::UnsupportedFormat => {
            RecoveryReviewError::Review(error)
        }
        _ => RecoveryReviewError::Source(error),
    }
}

fn census_error(error: StoreError) -> RecoveryReviewError {
    // observe/finish perform bookkeeping only; their Unavailable denotes the
    // original finite deadline, never a physical device fault or inferred abort.
    if error == StoreError::Unavailable {
        RecoveryReviewError::Deadline
    } else {
        source(error)
    }
}

fn contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<tenant::TenantCensusContribution, StoreError> {
    match atomic::tenant_census_contribution(view, key, bytes) {
        Err(StoreError::UnsupportedFormat) => {
            match DispatchCatalog::tenant_census_contribution(view, key, bytes) {
                Err(StoreError::UnsupportedFormat) => tenant::census_contribution(view, key, bytes),
                result => result,
            }
        }
        result => result,
    }
}

fn atomic_error(error: AtomicError) -> RecoveryReviewError {
    source(match error {
        AtomicError::UnsupportedFormat => StoreError::UnsupportedFormat,
        AtomicError::Limit => StoreError::Capacity,
        _ => StoreError::Corrupt,
    })
}
