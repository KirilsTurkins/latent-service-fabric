//! Closed snapshot producer over original Recovery custody and native capacity.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::native_capacity::NativeReservation;

use super::custody::{ProtectedCustodyJob, ProtectedStoreCustody};
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{ReadView, RowKey, StoreError};
use crate::recovery::snapshot::{
    export_reviewed_snapshot, inspect_snapshot, RequiredArtifact, SnapshotClosure, SnapshotError,
    SnapshotMetadata, SnapshotReceipt,
};
use crate::store_io::{StoreIoError, StoreIoKind, StoreIoRetirement, StoreIoRetirementWitness};

mod native;
mod response;
pub(super) use native::SnapshotFile;
pub use response::{
    ProtectedSnapshotManifestFrame, ProtectedSnapshotReceipt, ProtectedSnapshotReceiptJob,
    SnapshotReceiptOwners, SnapshotReceiptReadFence, SNAPSHOT_RECEIPT_RESPONSE_BYTES,
};

const RESOURCE_BYTES: u64 = 64 * 1024;
const WORK_BYTES: u64 = 8 * 1024 * 1024;

/// Trusted operator configuration. A transport resolves a bounded configured
/// destination ID to this private root; client paths are never accepted here.
#[derive(Clone, Debug)]
pub struct ProtectedSnapshotConfig {
    pub root: PathBuf,
    pub file_name: String,
}

impl ProtectedSnapshotConfig {
    fn validate(&self) -> Result<u64, ProtectedStoreError> {
        if !self.root.is_absolute()
            || self.root.as_os_str().is_empty()
            || self.root.as_os_str().len() > 4096
            || self.root.capacity() > 4096
            || self.file_name.is_empty()
            || self.file_name.len() > 128
            || self.file_name.capacity() > 128
            || self.file_name == "."
            || self.file_name == ".."
            || !self
                .file_name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        Ok(RESOURCE_BYTES)
    }
}

/// The same affine resource owns native file/root, original deadline/capacity
/// and exclusive engine custody. Metadata/readback success is not retirement:
/// the service must retire this resource before reopening business admission.
#[must_use = "retain exclusive custody through actual snapshot resource retirement"]
pub struct ProtectedSnapshot {
    pub(super) custody: ProtectedStoreCustody<Option<SnapshotFile>>,
}

impl ProtectedSnapshot {
    pub fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.custody.retirement_witness()
    }

    pub fn retire(self) -> StoreIoRetirement {
        self.custody.retire()
    }
}

#[must_use = "waiter loss detaches accepted export; it cannot release physical custody"]
pub struct ProtectedSnapshotJob {
    inner: ProtectedCustodyJob<Option<SnapshotFile>, Result<SnapshotReceipt, SnapshotError>>,
}

impl Future for ProtectedSnapshotJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<SnapshotReceipt, SnapshotError>, ProtectedStoreError>,
        ),
        StoreIoError,
    >;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(cx) {
            Poll::Ready(Ok((custody, result))) => {
                Poll::Ready(Ok((ProtectedSnapshot { custody }, result)))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ProtectedStoreOwner {
    /// Reopen an explicitly configured existing checkpoint after actual prior
    /// resource retirement/restart. The fresh Recovery request authorizes only
    /// present input access; immutable command/effect/migration identities and
    /// old execution grants are not renewed. Missing/partial files refuse.
    pub fn open_snapshot(
        &self,
        config: ProtectedSnapshotConfig,
        original: Arc<NativeReservation>,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
        current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
        let bytes = config.validate()?;
        let custody = self.reserve_custody(bytes, WORK_BYTES, Arc::clone(&original))?;
        let inner = self.initialize_custody_with(custody, WORK_BYTES, move |store| {
            let file = match SnapshotFile::open_existing(store, config, original, current) {
                Ok(file) => file,
                Err(SnapshotError::Source(error)) => return Err(error),
                Err(error) => return Ok((None, Err(error))),
            };
            let receipt = inspect_snapshot(&mut file.cursor(), file.deadline(), validate_row)
                .map_err(SnapshotError::Review);
            Ok((Some(file), receipt))
        })?;
        Ok(ProtectedSnapshotJob { inner })
    }

    /// Export one physically quiesced source to an exclusively created private
    /// operator file. All ten row families and exact immutable associations are
    /// captured from the same native snapshot; the complete bounded stream is
    /// fsynced and decoded/read back before a receipt is returned.
    ///
    /// Review callbacks are installed trusted codec/artifact owners. `current`
    /// is the original authenticated read/critical-audit currentness check: short
    /// metadata only, no guest, I/O or authority renewal. It is checked around
    /// every external file operation outside storage bookkeeping locks. No
    /// callback may treat these descriptive IDs or the receipt as authorization.
    #[allow(clippy::too_many_arguments)] // Separate mandatory codec/artifact/currentness owners.
    pub fn create_snapshot(
        &self,
        config: ProtectedSnapshotConfig,
        metadata: SnapshotMetadata,
        original: Arc<NativeReservation>,
        validate: impl FnOnce(&ReadView) -> Result<SnapshotClosure, StoreError> + Send + 'static,
        verify_artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError> + Send + 'static,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
        current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
        self.create_reviewed_snapshot(
            config,
            metadata,
            original,
            |view| validate(view).map_err(SnapshotError::source),
            verify_artifact,
            validate_row,
            current,
        )
    }

    /// Typed installed-owner review on the same original snapshot implementation.
    /// Healthy catalog/current-access/decoder/deadline refusal is independent
    /// from actual physical corruption or uncertain store I/O. This adds no
    /// owner, path, grant, lease, fallback engine or deadline extension.
    #[allow(clippy::too_many_arguments)] // Separate mandatory codec/artifact/currentness owners.
    pub fn create_reviewed_snapshot(
        &self,
        config: ProtectedSnapshotConfig,
        metadata: SnapshotMetadata,
        original: Arc<NativeReservation>,
        validate: impl FnOnce(&ReadView) -> Result<SnapshotClosure, SnapshotError> + Send + 'static,
        verify_artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError> + Send + 'static,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
        current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
        let bytes = config.validate()?;
        metadata.validate().map_err(ProtectedStoreError::Store)?;
        let custody = self.reserve_custody(bytes, WORK_BYTES, Arc::clone(&original))?;
        let inner = self.initialize_custody_with(custody, WORK_BYTES, move |store| {
            let file = match SnapshotFile::create(store, config, Arc::clone(&original), current) {
                Ok(file) => file,
                Err(SnapshotError::Source(error)) => return Err(error),
                Err(error) => return Ok((None, Err(error))),
            };
            let outcome = export_reviewed_snapshot(
                store.engine(),
                metadata,
                &mut file.cursor(),
                original.original_deadline(),
                validate,
                verify_artifact,
            )
            .and_then(|receipt| file.verify(receipt, validate_row));
            match outcome {
                Err(SnapshotError::Source(error)) => Err(error),
                outcome => Ok((Some(file), outcome)),
            }
        })?;
        Ok(ProtectedSnapshotJob { inner })
    }

    /// Reinspect the SAME affine file without opening a client-selected path or
    /// changing its original deadline. Expired/changed input never becomes an
    /// absent snapshot or an authorization to restore another source.
    pub fn inspect_created_snapshot(
        &self,
        snapshot: ProtectedSnapshot,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
    ) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryRead,
            WORK_BYTES,
            move |file, _| {
                let Some(file) = file else {
                    return Ok(Err(SnapshotError::Review(StoreError::Invalid)));
                };
                Ok(
                    inspect_snapshot(&mut file.cursor(), file.deadline(), validate_row)
                        .map_err(SnapshotError::Review),
                )
            },
        )?;
        Ok(ProtectedSnapshotJob { inner })
    }
}
