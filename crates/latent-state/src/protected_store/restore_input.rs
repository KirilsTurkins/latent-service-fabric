//! Nonmutating restore input review under the original affine snapshot custody.
//! The destination's Fresh/checkpoint/control admission uses its actual owners.

use super::{
    custody::ProtectedCustodyJob, snapshot::SnapshotFile, ProtectedSnapshot, ProtectedStoreError,
    ProtectedStoreOwner,
};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    inbox_scope::InboxScopeInventory,
    recovery::{
        restore::RestoreWindow,
        snapshot::{RequiredArtifact, SnapshotClosure, SnapshotError, SnapshotReceipt},
    },
    store_identity::InboxCustodyWatermark,
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::{
    NativeBufferClass, NativeBufferPermit, NativeCapacityError, NativeReservation,
};
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

/// Finite decoded snapshot/window/closure metadata plus one canonical window
/// frame. The source manifest and window each admit at most 128 namespaces and
/// 1 MiB encoded metadata; all record, format and artifact collections remain
/// bounded. This is a response charge on the SAME original reservation, separate
/// from its existing 8 MiB worker scratch charge and private archive file.
pub const RESTORE_INPUT_RESPONSE_BYTES: u64 = 8 * 1024 * 1024;

/// Exact input preconditions only. Knowing either digest supplies no read,
/// cross-tenant, migration, restore, provider or resume authority.
pub struct RestoreInputPrecondition {
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
}

/// Installed same-unit authorization/audit and immutable decoder/catalog
/// owners. Linked review uses the SAME borrowed native view and actual tenant
/// quotas; input metadata never selects an allowed tenant. No callback defaults
/// to allowed. Review runs outside currentness locks on the fixed Recovery
/// worker; `accept_read` is a short no-I/O original-policy/namespace/native fence.
pub trait RestoreInputOwners: Send + Sync + 'static {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError>;
    fn current_closure(&self, view: &ReadView) -> Result<SnapshotClosure, SnapshotError>;
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn review_window(&self, view: &ReadView, window: &RestoreWindow) -> Result<(), StoreError>;
    /// Same installed current read/audit/artifact decisions at every physical
    /// response check. No fresh owner, callback default or renewed grant.
    fn current(&self) -> Result<(), StoreError>;
    fn accept_read(&self, original: RestoreReadFence<'_>) -> Result<(), StoreError>;
}

/// Affine final original-native check. This accepts a metadata read only; it
/// supplies no original-command retry, technical abort or restore approval.
pub struct RestoreReadFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
}
impl RestoreReadFence<'_> {
    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(native_error)
    }
}

/// Nonclone input/read descriptions. Metadata and installed inputs precede the
/// prepaid buffer/native owner in destruction order, even after file retirement.
/// Final staged links, current controls, Fresh ownership and reconciliation remain
/// mandatory; this read result creates none of those authorities.
pub struct ProtectedRestoreInput {
    snapshot: SnapshotReceipt,
    current: SnapshotClosure,
    window: RestoreWindow,
    inbox_custody: Option<InboxCustodyWatermark>,
    inbox_history: Option<InboxHistoryComparison>,
    current_check: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    owners: Arc<dyn RestoreInputOwners>,
    buffer: NativeBufferPermit,
    original: Arc<NativeReservation>,
}
impl ProtectedRestoreInput {
    pub(super) fn original(&self) -> Arc<NativeReservation> {
        Arc::clone(&self.original)
    }
    pub(super) fn is_from_file(&self, file: &SnapshotFile) -> bool {
        Arc::ptr_eq(&self.original, &file.retain_original())
            && Arc::ptr_eq(&self.current_check, &file.retain_current())
    }
    #[must_use]
    pub const fn snapshot(&self) -> &SnapshotReceipt {
        &self.snapshot
    }
    #[must_use]
    pub const fn current(&self) -> &SnapshotClosure {
        &self.current
    }
    #[must_use]
    pub const fn window(&self) -> &RestoreWindow {
        &self.window
    }

    #[must_use]
    pub const fn inbox_custody(&self) -> Option<InboxCustodyWatermark> {
        self.inbox_custody
    }

    #[must_use]
    pub const fn inbox_history(&self) -> Option<InboxHistoryComparison> {
        self.inbox_history
    }

    pub(super) fn verify_inbox_custody(&self, view: &ReadView) -> Result<(), StoreError> {
        require_inbox_custody(view, &self.original, self.inbox_custody)
    }

    #[must_use]
    pub fn response_bytes(&self) -> u64 {
        self.buffer.bytes()
    }

    pub fn check(&self) -> Result<(), SnapshotError> {
        self.original
            .with_live(|| ())
            .map_err(native_snapshot_error)?;
        (self.current_check)().map_err(SnapshotError::Review)?;
        self.owners.current().map_err(SnapshotError::Review)
    }

    pub(super) fn accept_read(&self) -> Result<(), StoreError> {
        let consumed = Cell::new(false);
        self.owners.accept_read(RestoreReadFence {
            original: &self.original,
            consumed: &consumed,
        })?;
        if !consumed.get() {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }

    /// Encode only the finite descriptive loss window under the already prepaid
    /// response. The transport must retain this same owner through frame drop.
    pub fn encode_window(self) -> Result<ProtectedRestoreWindowFrame, SnapshotError> {
        self.check()?;
        let bytes = self
            .window
            .canonical_bytes()
            .map_err(SnapshotError::Review)?;
        self.check()?;
        Ok(ProtectedRestoreWindowFrame { bytes, owner: self })
    }
}

/// Existing transport `Bytes::from_owner` can hold this nonclone frame. Encoded
/// bytes die before the decoded metadata, installed pins and original permit.
/// No detach-to-Vec method bypasses that physical destruction order.
pub struct ProtectedRestoreWindowFrame {
    bytes: Vec<u8>,
    owner: ProtectedRestoreInput,
}
impl ProtectedRestoreWindowFrame {
    #[must_use]
    pub fn input(&self) -> &ProtectedRestoreInput {
        &self.owner
    }

    pub fn check(&self) -> Result<(), SnapshotError> {
        self.owner.check()
    }
}
impl AsRef<[u8]> for ProtectedRestoreWindowFrame {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}

#[must_use = "accepted input review and private file custody survive waiter loss"]
pub struct ProtectedRestoreInputJob {
    inner: ProtectedCustodyJob<Option<SnapshotFile>, Result<ProtectedRestoreInput, SnapshotError>>,
}
impl Future for ProtectedRestoreInputJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<ProtectedRestoreInput, SnapshotError>, ProtectedStoreError>,
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
    /// Reread the actual SAME private file and current unit, using its original
    /// global reservation, absolute deadline and pre-reserved Recovery worker.
    /// No path/engine escapes, native owner is replaced, or mutable batch exists.
    pub fn review_restore_window(
        &self,
        snapshot: ProtectedSnapshot,
        expected: RestoreInputPrecondition,
        owners: Arc<dyn RestoreInputOwners>,
    ) -> Result<ProtectedRestoreInputJob, ProtectedStoreError> {
        if expected.snapshot_digest == [0; 32] || expected.manifest_digest == [0; 32] {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let work = snapshot.custody.maximum_job_bytes();
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryRead,
            work,
            move |file, store| {
                let Some(file) = file else {
                    return Ok(Err(SnapshotError::Review(StoreError::Invalid)));
                };
                if let Err(error) = file.retain_restore_input_owner(&owners) {
                    return Ok(Err(SnapshotError::Review(error)));
                }
                let result = review(file, store, &expected, owners);
                match result {
                    Err(SnapshotError::Source(error)) => Err(error),
                    result => Ok(result),
                }
            },
        )?;
        Ok(ProtectedRestoreInputJob { inner })
    }
}

fn review(
    file: &SnapshotFile,
    store: &crate::embedded::EmbeddedStore,
    expected: &RestoreInputPrecondition,
    owners: Arc<dyn RestoreInputOwners>,
) -> Result<ProtectedRestoreInput, SnapshotError> {
    let original = file.retain_original();
    // These locals are declared before any decoded metadata. Early refusal and
    // detached completions destroy that metadata before refunding the permit.
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, RESTORE_INPUT_RESPONSE_BYTES)
        .map_err(native_snapshot_error)?;
    owners.current().map_err(SnapshotError::Review)?;
    file.check()
        .map_err(|_| SnapshotError::Review(StoreError::Unavailable))?;
    let mut archived_inbox = InboxHistory::default();
    let (snapshot, inbox_custody) = file
        .inspect_inbox_custody(
            |key, bytes| owners.archive_row(key, bytes),
            |key, bytes| archived_inbox.observe(key, bytes),
        )
        .map_err(SnapshotError::Review)?;
    if snapshot.snapshot_digest != expected.snapshot_digest
        || snapshot.manifest_digest != expected.manifest_digest
    {
        return Err(SnapshotError::Review(StoreError::Conflict));
    }
    for artifact in &snapshot.manifest.metadata.required_artifacts {
        file.check()
            .map_err(|_| SnapshotError::Review(StoreError::Unavailable))?;
        owners
            .required_artifact(artifact)
            .map_err(SnapshotError::Review)?;
    }
    let view = store.snapshot().map_err(SnapshotError::source)?;
    let current = owners.current_closure(&view)?;
    require_finite_closure(&current)?;
    require_inbox_custody(&view, &original, inbox_custody).map_err(SnapshotError::Review)?;
    let mut current_inbox = InboxHistory::default();
    let window = RestoreWindow::capture_observed(
        &view,
        &snapshot,
        file.deadline(),
        || file.original().with_live(|| ()).map_err(native_error),
        |key, bytes| current_inbox.observe(key, bytes),
    )?;
    let inbox_history = inbox_custody.map(|_| archived_inbox.compare(current_inbox));
    owners
        .review_window(&view, &window)
        .map_err(SnapshotError::Review)?;
    file.check()
        .map_err(|_| SnapshotError::Review(StoreError::Unavailable))?;
    let consumed = Cell::new(false);
    owners
        .accept_read(RestoreReadFence {
            original: file.original(),
            consumed: &consumed,
        })
        .map_err(|error| {
            if error == StoreError::SnapshotExpired {
                SnapshotError::Deadline
            } else {
                SnapshotError::Review(error)
            }
        })?;
    if !consumed.get() {
        return Err(SnapshotError::Review(StoreError::Invalid));
    }
    drop(view);
    let input = ProtectedRestoreInput {
        snapshot,
        current,
        window,
        inbox_custody,
        inbox_history,
        current_check: file.retain_current(),
        owners,
        buffer,
        original,
    };
    input.check()?;
    Ok(input)
}

/// Compares the exact terminal inbox protections retained by each history.
/// Pending attempts and broker acknowledgement positions are separate facts.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InboxHistoryComparison {
    pub archived_rows: u64,
    pub current_rows: u64,
    pub identical: bool,
}

#[derive(Default)]
struct InboxHistory {
    rows: u64,
    hash: Sha256,
}
impl InboxHistory {
    fn observe(&mut self, key: &RowKey, value: &[u8]) {
        if key.family == Family::Inbox {
            // The archive and original view walks already bound row counts,
            // keys and values before invoking the observer.
            self.rows += 1;
            for bytes in [&key.key[..], value] {
                self.hash.update((bytes.len() as u64).to_le_bytes());
                self.hash.update(bytes);
            }
        }
    }

    fn compare(self, current: Self) -> InboxHistoryComparison {
        InboxHistoryComparison {
            archived_rows: self.rows,
            current_rows: current.rows,
            identical: self.rows == current.rows && self.hash.finalize() == current.hash.finalize(),
        }
    }
}

fn require_inbox_custody(
    view: &ReadView,
    original: &NativeReservation,
    expected: Option<InboxCustodyWatermark>,
) -> Result<(), StoreError> {
    let observed =
        InboxScopeInventory::read(view, || original.with_live(|| ()).map_err(native_error))?;
    if observed != expected {
        return Err(StoreError::Conflict);
    }
    Ok(())
}

fn require_finite_closure(current: &SnapshotClosure) -> Result<(), SnapshotError> {
    if current.required_artifacts.len() > crate::recovery::snapshot::SNAPSHOT_ARTIFACTS
        || current.required_artifacts.capacity() > crate::recovery::snapshot::SNAPSHOT_ARTIFACTS
    {
        return Err(SnapshotError::Capacity);
    }
    for artifact in &current.required_artifacts {
        crate::namespace::identity(&artifact.identity).map_err(|_| SnapshotError::Capacity)?;
        if artifact.identity.capacity() > 256 || artifact.digest == [0; 32] {
            return Err(SnapshotError::Capacity);
        }
    }
    for format in current.inventory.entries().keys() {
        if format.identity.capacity() > 256 {
            return Err(SnapshotError::Capacity);
        }
    }
    Ok(())
}

fn native_error(error: NativeCapacityError) -> StoreError {
    if error == NativeCapacityError::DeadlineExceeded {
        StoreError::SnapshotExpired
    } else {
        StoreError::Unavailable
    }
}

fn native_snapshot_error(error: NativeCapacityError) -> SnapshotError {
    match error {
        NativeCapacityError::DeadlineExceeded => SnapshotError::Deadline,
        NativeCapacityError::BufferLimit
        | NativeCapacityError::BufferTooLarge
        | NativeCapacityError::AllocationFailed => SnapshotError::Capacity,
        _ => SnapshotError::Review(StoreError::Unavailable),
    }
}

#[cfg(test)]
mod inbox_history_tests {
    use super::{Family, InboxHistory, RowKey};

    #[test]
    fn same_count_with_replaced_terminal_protection_is_detected() {
        let inbox = RowKey {
            family: Family::Inbox,
            key: b"input:17".to_vec(),
        };
        let command = RowKey {
            family: Family::Command,
            key: b"pending:18".to_vec(),
        };
        let mut archived = InboxHistory::default();
        archived.observe(&inbox, b"original protection");
        let mut current = InboxHistory::default();
        current.observe(&inbox, b"changed protection");
        current.observe(&command, b"pending");

        let comparison = archived.compare(current);
        assert_eq!((comparison.archived_rows, comparison.current_rows), (1, 1));
        assert!(!comparison.identical);
    }
}
