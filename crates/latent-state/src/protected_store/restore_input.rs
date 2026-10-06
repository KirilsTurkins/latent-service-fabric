//! Nonmutating restore input review under the original affine snapshot custody.
//! The destination's Fresh/checkpoint/control admission uses its actual owners.

use super::{
    custody::ProtectedCustodyJob, snapshot::SnapshotFile, ProtectedSnapshot, ProtectedStoreError,
    ProtectedStoreOwner,
};
use crate::{
    embedded::{ReadView, RowKey, StoreError},
    recovery::{
        restore::RestoreWindow,
        snapshot::{
            inspect_snapshot, RequiredArtifact, SnapshotClosure, SnapshotError, SnapshotReceipt,
        },
    },
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::{
    NativeBufferClass, NativeBufferPermit, NativeCapacityError, NativeReservation,
};
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
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
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
    let snapshot = inspect_snapshot(&mut file.cursor(), file.deadline(), |key, bytes| {
        owners.archive_row(key, bytes)
    })
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
    let window = RestoreWindow::capture(&view, &snapshot, file.deadline(), || {
        file.original().with_live(|| ()).map_err(native_error)
    })?;
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
        current_check: file.retain_current(),
        owners,
        buffer,
        original,
    };
    input.check()?;
    Ok(input)
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
