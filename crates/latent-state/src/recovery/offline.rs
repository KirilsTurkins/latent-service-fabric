//! Qualified Linux/ext4 offline workflow on the existing fixed storage owner.
//! Exclusive source ownership proves actual engine/dispatcher/view retirement;
//! this facade exposes no ordinary command, query, commit or dispatch method.

mod file;
mod operation;
mod startup;

pub use operation::OfflineOperation;
pub use startup::OfflineRecoveryStartup;

use super::{
    restore::{RestoreRequest, RestoreWindow},
    snapshot::{RequiredArtifact, SnapshotClosure, SnapshotMetadata, SnapshotReceipt},
    RecoveryGuard,
};
use crate::{
    embedded::{ReadView, RowKey, StoreError},
    namespace::compatibility::RetainedFormat,
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
