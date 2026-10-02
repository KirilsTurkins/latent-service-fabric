//! Nonmutating restore input review under the original affine snapshot custody.
//! The new destination's Fresh/checkpoint/control admission remains Root-owned.

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
use latent_core::native_capacity::{NativeCapacityError, NativeReservation};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

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

/// Complete input/read descriptions only. Final staged imported links, current
/// controls, fresh ownership and explicit reconciliation remain mandatory.
pub struct ProtectedRestoreInput {
    snapshot: SnapshotReceipt,
    current: SnapshotClosure,
    window: RestoreWindow,
}
impl ProtectedRestoreInput {
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
                let result = review(file, store, &expected, &owners);
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
    owners: &Arc<dyn RestoreInputOwners>,
) -> Result<ProtectedRestoreInput, SnapshotError> {
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
    Ok(ProtectedRestoreInput {
        snapshot,
        current,
        window,
    })
}

fn native_error(error: NativeCapacityError) -> StoreError {
    if error == NativeCapacityError::DeadlineExceeded {
        StoreError::SnapshotExpired
    } else {
        StoreError::Unavailable
    }
}
