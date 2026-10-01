//! Qualified Linux/ext4 offline workflow on the existing fixed storage owner.
//! Exclusive source ownership proves actual engine/dispatcher/view retirement;
//! this facade exposes no ordinary command, query, commit or dispatch method.

mod file;
mod migration;
mod operation;
mod review;
mod startup;

pub use operation::OfflineOperation;
pub use startup::OfflineRecoveryStartup;

use super::{
    migration::{
        AggregateMigrationObservation, AggregateMigrationProgress, AggregateMigrationRequest,
        MigrationAction,
    },
    restore::{RestoreRequest, RestoreWindow},
    resume::{
        NamespaceRecoveryView, NamespaceResumeObservation, NamespaceResumeReceipt,
        NamespaceResumeRequest,
    },
    snapshot::{RequiredArtifact, SnapshotClosure, SnapshotMetadata, SnapshotReceipt},
    RecoveryGuard,
};
use crate::{
    embedded::{ReadView, RowKey, StoreError},
    namespace::compatibility::{RetainedFormat, ReviewedSchema},
    protected_store::{
        ProtectedStoreConfig, ProtectedStoreDrain, ProtectedStoreError, ProtectedStoreOwner,
    },
    store_io::StoreIoSnapshot,
};
use std::{
    future::Future,
    path::PathBuf,
    sync::{atomic::AtomicBool, Arc},
    time::Instant,
};

/// Installed host codecs/review owner, never a request-selected plugin. Methods
/// run on the existing fixed physical worker, use finite local/protected inputs,
/// and cannot execute guests or provider effects. Linked validation must include
/// every retained record and payload and its original immutable associations.
pub trait RecoveryCodecs: Send + Sync + 'static {
    fn runtime_digest(&self) -> [u8; 32];
    fn retained_bytes(&self) -> u64;
    fn scratch_bytes(&self) -> u64;
    fn installed_formats(&self) -> &[RetainedFormat];
    fn validate_row(&self, source: &ReadView, key: &RowKey, value: &[u8])
        -> Result<(), StoreError>;
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError>;
    fn verify_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        output: &SnapshotFile,
    ) -> Result<(), StoreError>;
    fn authorize_inspection(
        &self,
        view: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError>;
    fn review_restore(
        &self,
        view: &ReadView,
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError>;

    /// Review the actual linked restored inventory, recovery/data-loss window,
    /// present grants and conservative clock continuity. No external redrive.
    fn review_reconciliation(
        &self,
        _view: &ReadView,
        _request: &RecoveryReviewRequest,
    ) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    /// Short no-I/O currentness check at the actual irreversible writer fence.
    fn accept_reconciliation(&self, _request: &RecoveryReviewRequest) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    fn review_namespace_resume(
        &self,
        _view: &ReadView,
        _request: &NamespaceResumeRequest,
        _observed: NamespaceResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    /// Must recheck current permission, revocation, clock and lifecycle state;
    /// installed review evidence alone cannot authorize a later commit.
    fn accept_namespace_resume(&self, _request: &NamespaceResumeRequest) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    fn authorize_namespace_inspection(
        &self,
        _view: &ReadView,
        _operator_id: &str,
        _namespace: &latent_core::StateNamespaceId,
    ) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    /// Select installed tested schema evidence for the exact actual package.
    /// Request declarations and artifact names are never this approval.
    fn migration_schema(
        &self,
        _view: &ReadView,
        _request: &OfflineAggregateMigrationRequest,
    ) -> Result<ReviewedSchema, StoreError> {
        Err(StoreError::Unavailable)
    }
    /// Installed, finite data recipe selection. The default preserves the
    /// historical key; selecting this never grants migration or resume rights.
    fn migration_recipe(
        &self,
        _view: &ReadView,
        _request: &OfflineAggregateMigrationRequest,
    ) -> Result<super::migration::AggregateMigrationRecipe, StoreError> {
        Ok(super::migration::AggregateMigrationRecipe::Count)
    }
    fn review_migration(
        &self,
        _view: &ReadView,
        _request: &OfflineAggregateMigrationRequest,
        _observation: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
    /// Short no-I/O current authority, lifecycle and clock continuity fence.
    fn accept_migration(
        &self,
        _request: &OfflineAggregateMigrationRequest,
        _phase: MigrationAction,
    ) -> Result<(), StoreError> {
        Err(StoreError::Unavailable)
    }
}

#[derive(Debug, Clone)]
pub struct OfflineAggregateMigrationRequest {
    pub checkpoint: SnapshotFile,
    pub review: AggregateMigrationRequest,
}

#[derive(Debug, Clone)]
pub struct RecoveryReviewRequest {
    pub operator_id: String,
    pub expected_guard: RecoveryGuard,
    pub review_digest: [u8; 32],
}

#[derive(Debug, Clone)]
pub struct SnapshotFile {
    /// Explicit pre-existing protected directory, never a guest path.
    pub root: PathBuf,
    pub file_name: String,
}

#[derive(Debug, Clone)]
pub struct OfflineRestoreRequest {
    pub input: SnapshotFile,
    pub destination: ProtectedStoreConfig,
    pub review: RestoreRequest,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OfflineRecoveryError {
    InvalidConfiguration,
    Busy,
    UnsafeDestination,
    Input(StoreError),
    Review(StoreError),
    Target(StoreError),
    Protected(ProtectedStoreError),
}

#[derive(Debug, Clone)]
pub struct OfflineRestoreReceipt {
    pub guard: RecoveryGuard,
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
    /// Physical identity of the staged root, never activation authority.
    pub destination_identity: (u64, u64),
}

#[derive(Debug)]
pub struct OfflineRestoreInspection {
    pub snapshot: SnapshotReceipt,
    /// Actual source-backed proposed data-loss/reconciliation window. Reading
    /// this value grants neither restoration nor business resumption.
    pub window: RestoreWindow,
}

pub struct OfflineRecoverySource {
    owner: ProtectedStoreOwner,
    codecs: Arc<dyn RecoveryCodecs>,
    source_root: PathBuf,
    tenant: String,
    busy: Arc<AtomicBool>,
}

impl OfflineRecoverySource {
    /// Persist reviewed paused progress; leave data/schema unchanged. A dropped
    /// waiter does not refund accepted physical work. Restart never completes it
    /// automatically; the same attributable operation must explicitly finish.
    pub fn stage_aggregate_migration(
        &self,
        request: OfflineAggregateMigrationRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<AggregateMigrationProgress>, OfflineRecoveryError> {
        migration::execute(self, request, MigrationAction::Stage, deadline)
    }
    /// One finite atomic data/usage/schema/history/completion envelope. This
    /// continues the same reviewed operation and still does not resume business.
    pub fn complete_aggregate_migration(
        &self,
        request: OfflineAggregateMigrationRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<AggregateMigrationProgress>, OfflineRecoveryError> {
        migration::execute(self, request, MigrationAction::Complete, deadline)
    }
    pub fn inspect_namespace(
        &self,
        operator_id: String,
        namespace: latent_core::StateNamespaceId,
        deadline: Instant,
    ) -> Result<OfflineOperation<NamespaceRecoveryView>, OfflineRecoveryError> {
        review::inspect_namespace(self, operator_id, namespace, deadline)
    }
    pub fn review_reconciliation(
        &self,
        request: RecoveryReviewRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<RecoveryGuard>, OfflineRecoveryError> {
        review::reconcile(self, request, deadline)
    }

    pub fn resume_namespace(
        &self,
        request: NamespaceResumeRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<NamespaceResumeReceipt>, OfflineRecoveryError> {
        review::resume(self, request, deadline)
    }
    pub fn inspect_restore(
        &self,
        request: OfflineRestoreRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<OfflineRestoreInspection>, OfflineRecoveryError> {
        operation::inspect(self, request, deadline)
    }
    pub fn backup_to(
        &self,
        output: SnapshotFile,
        metadata: SnapshotMetadata,
        deadline: Instant,
    ) -> Result<OfflineOperation<SnapshotReceipt>, OfflineRecoveryError> {
        operation::backup(self, output, metadata, deadline)
    }

    pub fn restore_to(
        &self,
        request: OfflineRestoreRequest,
        deadline: Instant,
    ) -> Result<OfflineOperation<OfflineRestoreReceipt>, OfflineRecoveryError> {
        operation::restore(self, request, deadline)
    }

    pub fn snapshot(&self) -> Result<StoreIoSnapshot, ProtectedStoreError> {
        self.owner.snapshot()
    }
    pub fn close(&self) {
        self.owner.close();
    }
    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        wait: F,
    ) -> Result<ProtectedStoreDrain<F>, ProtectedStoreError> {
        self.owner.drain_async(deadline, wait)
    }
    pub fn reap_retired_threads(&self) -> Result<usize, ProtectedStoreError> {
        self.owner.reap_retired_threads()
    }
}

impl Drop for OfflineRecoverySource {
    fn drop(&mut self) {
        self.owner.close();
    }
}

const CODEC_BYTES: u64 = 4 * 1024 * 1024;
const OPERATION_SCRATCH_BYTES: u64 = 32 * 1024 * 1024;

#[cfg(test)]
mod tests;
